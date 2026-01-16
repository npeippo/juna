# Tallenna tämä tiedostoon app.py, jos käytät Streamlitia
import streamlit as st
import requests
import math
from datetime import date, datetime, timedelta

# --- ASETUKSET ---
st.set_page_config(page_title="Juna-apuri", page_icon="🚆")
headers = { "Digitraffic-User": "MobiiliDev/Streamlit-1.0" }

# --- APUFUNKTIOT ---
def get_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def parse_time_str(t_str): return t_str.split('.')[0].replace('Z', '')
def parse_dt(t_str): return datetime.fromisoformat(t_str.replace('Z', '+00:00'))

@st.cache_data(ttl=3600) # Välimuisti asemille (nopeuttaa sovellusta)
def get_stations():
    try:
        resp = requests.get("https://rata.digitraffic.fi/api/v1/metadata/stations", headers=headers)
        return {s['stationShortCode']: (s['latitude'], s['longitude']) for s in resp.json()}
    except:
        return {}

# --- PÄÄOHJELMA ---
st.title("🚆 Keskinopeuslaskuri")
st.write("Näe tarkka etäisyys ja vaadittu nopeus seuraavalle asemalle.")

station_map = get_stations()

# Syötekenttä
col1, col2 = st.columns([3, 1])
with col1:
    # Streamlitissa Enter toimii oletuksena tässä
    train_num_input = st.text_input("Junan numero", placeholder="Esim. 11")
with col2:
    st.write("") 
    st.write("")
    refresh = st.button("🔄") # Päivitä-nappi

if train_num_input:
    if not train_num_input.isdigit():
        st.error("Syötä pelkkä numero.")
    else:
        train_number = int(train_num_input)
        today_str = date.today().isoformat()
        
        with st.spinner(f"Haetaan tietoja junalle {train_number}..."):
            try:
                # Haetaan tiedot
                t_resp = requests.get(f"https://rata.digitraffic.fi/api/v1/trains/{today_str}/{train_number}", headers=headers)
                trains = t_resp.json()

                if not trains:
                    st.warning(f"Junaa {train_number} ei löydy tälle päivälle.")
                else:
                    train = trains[0]
                    l_resp = requests.get(f"https://rata.digitraffic.fi/api/v1/train-locations/latest/{train_number}", headers=headers)
                    loc_data = l_resp.json()

                    if not loc_data:
                        st.warning("Juna löytyi, mutta GPS-tietoa ei saada.")
                    else:
                        # Datan käsittely
                        curr_lat = loc_data[0]['location']['coordinates'][1]
                        curr_lon = loc_data[0]['location']['coordinates'][0]
                        current_speed = loc_data[0].get('speed', 0)
                        gps_dt = parse_dt(loc_data[0]['timestamp'])
                        gps_time_cmp = parse_time_str(loc_data[0]['timestamp'])
                        
                        # Tulostetaan perustiedot
                        st.info(f"Sijainti: {curr_lat:.4f}, {curr_lon:.4f} | Nopeus: {current_speed} km/h")
                        
                        # Logiikka
                        rows = train['timeTableRows']
                        next_waypoint_index = -1
                        for i, row in enumerate(rows):
                            if "actualTime" in row: continue
                            row_cmp = parse_time_str(row.get('liveEstimateTime', row['scheduledTime']))
                            if row_cmp < gps_time_cmp: continue 
                            next_waypoint_index = i
                            break
                        
                        if next_waypoint_index == -1:
                            st.success("Juna on perillä!")
                        else:
                            # Seuraava pysähdys
                            target_index = -1
                            next_stop_row = None
                            for k in range(next_waypoint_index, len(rows)):
                                r = rows[k]
                                if r['trainStopping'] and r['type'] == 'ARRIVAL':
                                    next_stop_row = r
                                    target_index = k
                                    break
                            
                            if next_stop_row:
                                dest = next_stop_row['stationShortCode']
                                sched_show = next_stop_row['scheduledTime'].split('T')[1][:5]
                                sched_dt = parse_dt(next_stop_row['scheduledTime'])
                                
                                st.header(f"Seuraava: {dest}")
                                st.subheader(f"Aikataulu: {sched_show}")
                                
                                # Etäisyys
                                total_dist = 0
                                fw = rows[next_waypoint_index]
                                if fw['stationShortCode'] in station_map:
                                    fw_lat, fw_lon = station_map[fw['stationShortCode']]
                                    total_dist += get_dist(curr_lat, curr_lon, fw_lat, fw_lon)
                                    prev_lat, prev_lon = fw_lat, fw_lon
                                    
                                    for k in range(next_waypoint_index + 1, target_index + 1):
                                        r = rows[k]
                                        if r['type'] == 'ARRIVAL' and r['stationShortCode'] in station_map:
                                            n_lat, n_lon = station_map[r['stationShortCode']]
                                            total_dist += get_dist(prev_lat, prev_lon, n_lat, n_lon)
                                            prev_lat, prev_lon = n_lat, n_lon
                                    
                                    # Visuaaliset mittarit
                                    col_a, col_b = st.columns(2)
                                    col_a.metric("Matkaa", f"{total_dist:.1f} km")
                                    
                                    time_left = (sched_dt - gps_dt).total_seconds()
                                    
                                    if time_left <= 0:
                                        col_b.metric("Status", "Myöhässä", delta_color="inverse")
                                        st.error("Vaadittu nopeus mahdoton.")
                                    else:
                                        req_speed = total_dist / (time_left / 3600)
                                        diff = req_speed - current_speed
                                        
                                        col_b.metric("Vaadittu nopeus", f"{req_speed:.0f} km/h", 
                                                     delta=f"{diff:.0f} km/h verrattuna nykyiseen",
                                                     delta_color="inverse") # Punainen jos vaaditaan kovempaa vauhtia
                                        
                                    st.markdown(f"[Avaa kartta](https://www.google.com/maps/search/?api=1&query={curr_lat},{curr_lon})")
                                else:
                                    st.warning("Reittipisteen koordinaatit puuttuvat.")
                            else:
                                st.write("Ei enää kaupallisia pysähdyksiä.")

            except Exception as e:
                st.error(f"Virhe: {e}")
