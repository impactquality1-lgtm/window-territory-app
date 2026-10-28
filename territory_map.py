import json
import urllib.request
import urllib.parse
import re
import folium
from folium.plugins import MarkerCluster

# Regional Parcel Endpoints
PARCEL_BASE_URLS = [
    "https://gis.hennepin.us/arcgis/rest/services/HennepinData/PROPERTY/MapServer/0/query?outFields=*&outSR=4326&f=json",
    "https://arcgis.metc.state.mn.us/data1/rest/services/parcels/Parcels/FeatureServer/3/query?outFields=*&outSR=4326&f=json"
]

# Common local shortcuts for instant lookup
KNOWN_BOUNDS = {
    "edina": {"lat_min": 44.842, "lat_max": 44.925, "lng_min": -93.385, "lng_max": -93.300},
    "55424": {"lat_min": 44.870, "lat_max": 44.910, "lng_min": -93.355, "lng_max": -93.315},
    "55435": {"lat_min": 44.842, "lat_max": 44.895, "lng_min": -93.385, "lng_max": -93.330},
    "55436": {"lat_min": 44.870, "lat_max": 44.925, "lng_min": -93.385, "lng_max": -93.340},
    "st. louis park": {"lat_min": 44.925, "lat_max": 44.985, "lng_min": -93.385, "lng_max": -93.310},
    "55416": {"lat_min": 44.935, "lat_max": 44.975, "lng_min": -93.355, "lng_max": -93.315},
    "minneapolis": {"lat_min": 44.890, "lat_max": 45.050, "lng_min": -93.330, "lng_max": -93.200}
}

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("features", [])
    except Exception as e:
        return []

def get_dynamic_bounds(search_term):
    """Dynamically geocodes any ZIP code or city name on the fly using OpenStreetMap."""
    term_low = search_term.strip().lower()
    if term_low in KNOWN_BOUNDS:
        return KNOWN_BOUNDS[term_low]
        
    # Append Minnesota context if not provided
    query = search_term
    if not any(st in query.lower() for st in ["mn", "minnesota", "usa", "united states"]):
        query += ", Minnesota"
        
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": "WindowSalesTerritoryBuilder/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            results = json.loads(response.read().decode("utf-8"))
            if results:
                box = results[0]["boundingbox"] # [lat_min, lat_max, lon_min, lon_max]
                return {
                    "lat_min": float(box[0]),
                    "lat_max": float(box[1]),
                    "lng_min": float(box[2]),
                    "lng_max": float(box[3])
                }
    except Exception as e:
        print(f"Warning: Could not geocode '{search_term}': {e}")
    return None

def get_centroid(geometry):
    if not geometry:
        return None, None
    if "x" in geometry and "y" in geometry:
        return geometry["y"], geometry["x"]
    if "rings" in geometry and geometry["rings"]:
        ring = geometry["rings"][0]
        lng = sum(pt[0] for pt in ring) / len(ring)
        lat = sum(pt[1] for pt in ring) / len(ring)
        return lat, lng
    return None, None

def get_year_built(attrs):
    for key, val in attrs.items():
        if key.lower() in ["yearbuilt", "year_built", "yrbuilt", "built_yr", "year_built_num"]:
            try:
                yr = int(val)
                if 1950 <= yr <= 1985:
                    return yr
            except (ValueError, TypeError):
                pass
    return None

def get_property_details(attrs):
    address = ""
    owner = "Unknown Owner"
    
    address_keys = ["situs_address", "site_address", "siteaddress", "prop_addr", "property_address", "address", "addr", "display"]
    for key, val in attrs.items():
        if any(ak == key.lower() for ak in address_keys) and val:
            val_str = str(val).strip()
            if val_str and val_str.lower() != "none":
                address = val_str
                break

    if not address:
        for key, val in attrs.items():
            k_low = key.lower()
            if any(term in k_low for term in ["addr", "situs", "location"]) and val:
                val_str = str(val).strip()
                if val_str and re.search(r'^\d+', val_str):
                    address = val_str
                    break

    if not address:
        address = "Address Unavailable"

    owner_keys = ["owner_name", "owner", "deed_holder", "taxpayer_name", "owner1", "deedname"]
    for key, val in attrs.items():
        if any(ok in key.lower() for ok in owner_keys) and val:
            val_str = str(val).strip()
            if val_str and val_str.lower() != "none":
                owner = val_str
                break

    return address, owner

def matches_turf(lat, lng, box):
    """Checks if coordinates fall within the dynamic bounding box."""
    if not box:
        return True
    return box["lat_min"] <= lat <= box["lat_max"] and box["lng_min"] <= lng <= box["lng_max"]

def build_territory_map():
    print("=== WINDOW SALES TERRITORY BUILDER ===")
    search_term = input("Enter target City name or ZIP code (e.g., Edina, Minnetonka, or 55345) [Press Enter for all metro]: ").strip()
    
    turf_bounds = None
    if search_term:
        print(loc_msg := f"\nLocating turf boundary for [{search_term}]...")
        turf_bounds = get_dynamic_bounds(search_term)
        if not turf_bounds:
            print("Could not resolve boundary. Falling back to full metro scope.")
            search_term = ""

    turf_label = search_term if search_term else "Entire Metro"
    print(f"Fetching target-era parcels for turf: [{turf_label}]...")
    
    raw_parcels = []
    seen_pids = set()
    year_chunks = [
        (1950, 1954), (1955, 1959),
        (1960, 1964), (1965, 1969),
        (1970, 1974), (1975, 1979),
        (1980, 1985)
    ]

    for base_url in PARCEL_BASE_URLS:
        for start_yr, end_yr in year_chunks:
            offset = 0
            batch_size = 2000
            sql_where = f"YEAR_BUILT >= {start_yr} AND YEAR_BUILT <= {end_yr}"
            
            while True:
                paged_url = f"{base_url}&where={urllib.parse.quote(sql_where)}&resultOffset={offset}&resultRecordCount={batch_size}"
                features = fetch_json(paged_url)
                
                if not features:
                    break
                
                for feat in features:
                    attrs = feat.get("attributes", {})
                    geometry = feat.get("geometry", {})
                    lat, lng = get_centroid(geometry)
                    
                    if not lat or not lng:
                        continue
                        
                    pid = str(attrs.get("PID") or attrs.get("PIN") or attrs.get("OBJECTID") or "")
                    if not pid or pid in seen_pids:
                        continue
                    seen_pids.add(pid)
                        
                    if turf_bounds and not matches_turf(lat, lng, turf_bounds):
                        continue
                            
                    raw_parcels.append((feat, lat, lng, pid))
                
                if len(features) < batch_size:
                    break
                offset += batch_size

    # Center map dynamically based on bounds or default to metro center
    map_center = [44.9778, -93.2650]
    zoom = 11
    if turf_bounds:
        map_center = [(turf_bounds["lat_min"] + turf_bounds["lat_max"]) / 2, (turf_bounds["lng_min"] + turf_bounds["lng_max"]) / 2]
        zoom = 13

    m = folium.Map(location=map_center, zoom_start=zoom, tiles="Esri.WorldStreetMap")
    
    cluster_50s = MarkerCluster(name="Target Homes: 1950–1959").add_to(m)
    cluster_60s = MarkerCluster(name="Target Homes: 1960–1969").add_to(m)
    cluster_70s_85 = MarkerCluster(name="Target Homes: 1970–1985").add_to(m)
    
    counts = {"50s": 0, "60s": 0, "70s_85": 0}
    property_lookup = {}

    for item, lat, lng, pid in raw_parcels:
        attrs = item.get("attributes", {})
        yr_built = get_year_built(attrs)
        if not yr_built:
            continue
            
        address, owner = get_property_details(attrs)
        safe_pid = re.sub(r'[^a-zA-Z0-9_]', '_', pid)

        property_lookup[safe_pid] = {
            "pid": pid,
            "address": address,
            "owner": owner,
            "yearBuilt": yr_built
        }

        popup_html = f"""
        <div style="font-family: sans-serif; font-size: 12px; width: 260px; line-height: 1.4;">
            <b style="color: #1d4ed8; font-size: 13px;">TARGET SALES OPPORTUNITY</b><br>
            <b>Address:</b> {address}<br>
            <b>Owner:</b> {owner}<br>
            <b>Year Built:</b> {yr_built}<br>
            <b>Parcel ID:</b> {pid}<br>
            <hr style="margin: 6px 0; border: none; border-top: 1px solid #cbd5e1;">
            <label style="font-weight: bold; color: #334155;">Sales Status:</label><br>
            <select id="status_{safe_pid}" style="width: 100%; margin-bottom: 6px; padding: 4px; border: 1px solid #cbd5e1; border-radius: 4px;">
                <option value="Unworked">-- Unworked --</option>
                <option value="Not Home">Not Home</option>
                <option value="Flier Left">Flier Left</option>
                <option value="Spoke to Owner">Spoke to Owner</option>
                <option value="Estimate Scheduled">Estimate Scheduled</option>
                <option value="Not Interested">Not Interested</option>
            </select>
            <label style="font-weight: bold; color: #334155;">Field Notes (max 250):</label><br>
            <textarea id="notes_{safe_pid}" maxlength="250" rows="3" style="width: 100%; resize: none; padding: 4px; border: 1px solid #cbd5e1; border-radius: 4px;" placeholder="Add notes..."></textarea>
            <button onclick="saveVisitData('{safe_pid}')" style="background: #2563eb; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; width: 100%; margin-top: 4px; font-weight: bold;">Save Visit</button>
        </div>
        <script>
        (function() {{
            let saved = localStorage.getItem('prop_' + '{safe_pid}');
            if (saved) {{
                let data = JSON.parse(saved);
                let sel = document.getElementById('status_' + '{safe_pid}');
                let txt = document.getElementById('notes_' + '{safe_pid}');
                if (sel) sel.value = data.status || 'Unworked';
                if (txt) txt.value = data.notes || '';
            }}
        }})();
        </script>
        """

        if 1950 <= yr_built <= 1959:
            folium.CircleMarker(
                location=[lat, lng], radius=4, color="#1e3a8a", fill=True, fill_color="#2563eb", fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=280)
            ).add_to(cluster_50s)
            counts["50s"] += 1
        elif 1960 <= yr_built <= 1969:
            folium.CircleMarker(
                location=[lat, lng], radius=4, color="#1e40af", fill=True, fill_color="#3b82f6", fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=280)
            ).add_to(cluster_60s)
            counts["60s"] += 1
        elif 1970 <= yr_built <= 1985:
            folium.CircleMarker(
                location=[lat, lng], radius=4, color="#2563eb", fill=True, fill_color="#60a5fa", fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=280)
            ).add_to(cluster_70s_85)
            counts["70s_85"] += 1

    property_lookup_json = json.dumps(property_lookup)
    global_script = f"""
    <script>
    const propertyMetadata = {property_lookup_json};

    function saveVisitData(pid) {{
        let status = document.getElementById('status_' + pid).value;
        let notes = document.getElementById('notes_' + pid).value;
        let data = {{ status: status, notes: notes, timestamp: new Date().toLocaleString() }};
        localStorage.setItem('prop_' + pid, JSON.stringify(data));
        alert('Visit saved successfully!');
    }}

    function exportFieldReport() {{
        let csvRows = ["Parcel ID,Address,Owner,Year Built,Status,Timestamp,Notes"];
        
        for (let safePid in propertyMetadata) {{
            let prop = propertyMetadata[safePid];
            let saved = localStorage.getItem('prop_' + safePid);
            
            let status = "Unworked";
            let timestamp = "";
            let notes = "";
            
            if (saved) {{
                let data = JSON.parse(saved);
                status = data.status || "Unworked";
                timestamp = data.timestamp || "";
                notes = (data.notes || "").replace(/,/g, " ").replace(/\\n/g, " ");
            }}
            
            if (status !== "Unworked" || notes !== "") {{
                let row = `"{{prop.pid}}","{{prop.address}}","{{prop.owner}}",{{prop.yearBuilt}},"{{status}}","{{timestamp}}","{{notes}}"`;
                csvRows.push(row);
            }}
        }}
        
        if (csvRows.length === 1) {{
            alert("No field visits recorded yet to export!");
            return;
        }}
        
        let csvString = csvRows.join("\\n");
        let blob = new Blob([csvString], {{ type: 'text/csv;charset=utf-8;' }});
        let url = URL.createObjectURL(blob);
        let link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", "turf_field_report.csv");
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }}
    </script>
    """
    m.get_root().html.add_child(folium.Element(global_script))

    total_parcels = sum(counts.values())
    display_turf = search_term if search_term else "Entire Metro"
    
    legend_html = f"""
    <div style="
        position: fixed; 
        bottom: 30px; left: 30px; width: 260px; 
        background-color: white; z-index:9999; font-size:13px; 
        border:2px solid #cbd5e1; border-radius: 8px; padding: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-family: sans-serif;">
      <b style="font-size: 14px; color: #0f172a;">Turf Summary: {display_turf.upper()}</b><br>
      <hr style="margin: 6px 0; border: none; border-top: 1px solid #e2e8f0;">
      <span style="color:#2563eb; font-size:16px;">■</span> <b>1950–1959:</b> {counts['50s']:,} homes<br>
      <span style="color:#3b82f6; font-size:16px;">■</span> <b>1960–1969:</b> {counts['60s']:,} homes<br>
      <span style="color:#60a5fa; font-size:16px;">■</span> <b>1970–1985:</b> {counts['70s_85']:,} homes<br>
      <hr style="margin: 6px 0; border: none; border-top: 1px solid #e2e8f0;">
      <b>Total Target Homes:</b> {total_parcels:,}<br><br>
      <button onclick="exportFieldReport()" style="background: #16a34a; color: white; border: none; padding: 8px 12px; border-radius: 6px; cursor: pointer; width: 100%; font-weight: bold; font-size: 13px;">📥 Export Field Report (CSV)</button>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl(collapsed=False).add_to(m)

    output_file = "window_sales_map.html"
    m.save(output_file)
    
    print(f"\n--- MAP GENERATED FOR: {display_turf.upper()} ---")
    print(f"Mapped {total_parcels} target homes across 3 decade tiers:")
    print(f"  - 1950-1959: {counts['50s']}")
    print(f"  - 1960-1969: {counts['60s']}")
    print(f"  - 1970-1985: {counts['70s_85']}")
    print(f"File saved to {output_file}.")

if __name__ == "__main__":
    build_territory_map()