import json
import urllib.request
import urllib.parse
import folium
from folium.plugins import HeatMap, MarkerCluster

# 1. Minneapolis Open Data - Active CCS Permits
PERMIT_API_URL = (
    "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/CCS_Permits/FeatureServer/0/query"
    "?where=1%3D1&outFields=*&outSR=4326&f=json&resultRecordCount=1000"
)

# 2. Both Regional Endpoints: Hennepin County + Full 7-County Met Council MetroGIS
PARCEL_BASE_URLS = [
    "https://gis.hennepin.us/arcgis/rest/services/HennepinData/PROPERTY/MapServer/0/query?outFields=*&outSR=4326&f=json",
    "https://arcgis.metc.state.mn.us/data1/rest/services/parcels/Parcels/FeatureServer/3/query?outFields=*&outSR=4326&f=json"
]

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("features", [])
    except Exception as e:
        return []

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

def get_address(attrs):
    """Checks all possible address column variations across county/regional schemas."""
    for key, val in attrs.items():
        if key.lower() in ["site_address", "siteaddress", "prop_addr", "parcel_address", "address", "display"]:
            if val and str(val).strip():
                return str(val).strip()
    return "Regional Property"

def fetch_all_metro_parcels():
    """Queries all regional endpoints across year chunks, aggregating and deduplicating records."""
    all_features = []
    seen_pids = set()
    
    year_chunks = [
        (1950, 1954),
        (1955, 1959),
        (1960, 1964),
        (1965, 1969),
        (1970, 1974),
        (1975, 1979),
        (1980, 1985)
    ]

    for i, base_url in enumerate(PARCEL_BASE_URLS):
        endpoint_name = "Hennepin County" if i == 0 else "Met Council 7-County Regional"
        print(f"\nQuerying endpoint: {endpoint_name}...")
        
        for start_yr, end_yr in year_chunks:
            offset = 0
            batch_size = 2000
            sql_where = f"YEAR_BUILT >= {start_yr} AND YEAR_BUILT <= {end_yr}"
            
            while True:
                paged_url = f"{base_url}&where={urllib.parse.quote(sql_where)}&resultOffset={offset}&resultRecordCount={batch_size}"
                features = fetch_json(paged_url)
                
                if not features:
                    break
                
                added_count = 0
                for feat in features:
                    attrs = feat.get("attributes", {})
                    pid = attrs.get("PID") or attrs.get("PIN") or attrs.get("OBJECTID")
                    
                    # Deduplicate across overlapping endpoints
                    if pid and pid in seen_pids:
                        continue
                    if pid:
                        seen_pids.add(pid)
                        
                    all_features.append(feat)
                    added_count += 1
                
                print(f"  -> Years {start_yr}–{end_yr}: Fetched {len(features)} (Added {added_count}, Cumulative Total: {len(all_features)})")
                
                if len(features) < batch_size:
                    break
                offset += batch_size
                
    return all_features

def build_territory_map():
    print("1. Fetching active window permit data...")
    permit_features = fetch_json(PERMIT_API_URL)
    
    print("\n2. Fetching full multi-source metro parcel data...")
    parcel_features = fetch_all_metro_parcels()

    # Center map on Minneapolis
    m = folium.Map(
        location=[44.9778, -93.2650], 
        zoom_start=11,
        tiles="Esri.WorldStreetMap"
    )
    
    permit_group = folium.FeatureGroup(name="Competitor Active Permits").add_to(m)
    
    cluster_50s = MarkerCluster(name="Target Homes: 1950–1959").add_to(m)
    cluster_60s = MarkerCluster(name="Target Homes: 1960–1969").add_to(m)
    cluster_70s_85 = MarkerCluster(name="Target Homes: 1970–1985").add_to(m)
    
    heat_data = []
    mapped_permits = 0
    counts = {"50s": 0, "60s": 0, "70s_85": 0}

    # --- PROCESS PERMITS ---
    for item in permit_features:
        attrs = item.get("attributes", {})
        geometry = item.get("geometry", {})
        lat, lng = get_centroid(geometry)
        if not lat or not lng:
            continue

        blob = " ".join([str(v) for v in attrs.values() if v is not None]).lower()
        if "window" in blob:
            heat_data.append([lat, lng])
            
            permit_no = attrs.get("permitNumber") or attrs.get("OBJECTID") or "N/A"
            address = get_address(attrs)
            contractor = attrs.get("applicantName") or "Unknown Contractor"
            description = attrs.get("comments") or "Window Replacement"

            popup_html = f"""
            <div style="font-family: sans-serif; font-size: 12px; width: 220px;">
                <b style="color: #b91c1c;">ACTIVE PERMIT</b><br>
                <b>Permit:</b> {permit_no}<br>
                <b>Address:</b> {address}<br>
                <b>Contractor:</b> {contractor}<br>
                <b>Scope:</b> {description}
            </div>
            """
            
            folium.CircleMarker(
                location=[lat, lng], radius=6, color="#b91c1c", fill=True, fill_color="#ef4444", fill_opacity=0.9,
                popup=folium.Popup(popup_html, max_width=250)
            ).add_to(permit_group)
            mapped_permits += 1

    # --- PROCESS PARCELS ---
    for item in parcel_features:
        attrs = item.get("attributes", {})
        geometry = item.get("geometry", {})
        lat, lng = get_centroid(geometry)
        if not lat or not lng:
            continue

        yr_built = get_year_built(attrs)
        if not yr_built:
            continue
            
        address = get_address(attrs)
        pid = attrs.get("PID") or attrs.get("PIN") or attrs.get("OBJECTID") or "N/A"

        popup_html = f"""
        <div style="font-family: sans-serif; font-size: 12px; width: 220px;">
            <b style="color: #1d4ed8;">TARGET SALES OPPORTUNITY</b><br>
            <b>Year Built:</b> {yr_built}<br>
            <b>Address:</b> {address}<br>
            <b>Parcel ID:</b> {pid}
        </div>
        """

        if 1950 <= yr_built <= 1959:
            folium.CircleMarker(
                location=[lat, lng], radius=4, color="#1e3a8a", fill=True, fill_color="#2563eb", fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=250)
            ).add_to(cluster_50s)
            counts["50s"] += 1
        elif 1960 <= yr_built <= 1969:
            folium.CircleMarker(
                location=[lat, lng], radius=4, color="#1e40af", fill=True, fill_color="#3b82f6", fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=250)
            ).add_to(cluster_60s)
            counts["60s"] += 1
        elif 1970 <= yr_built <= 1985:
            folium.CircleMarker(
                location=[lat, lng], radius=4, color="#2563eb", fill=True, fill_color="#60a5fa", fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=250)
            ).add_to(cluster_70s_85)
            counts["70s_85"] += 1

    if heat_data:
        HeatMap(heat_data, radius=15, blur=10, max_zoom=15).add_to(permit_group)

    folium.LayerControl(collapsed=False).add_to(m)

    output_file = "window_sales_map.html"
    m.save(output_file)
    
    total_parcels = sum(counts.values())
    print(f"\n--- MAP GENERATED ---")
    print(f"Mapped {mapped_permits} active window permits.")
    print(f"Mapped {total_parcels} target homes across the 7-County Metro:")
    print(f"  - 1950-1959: {counts['50s']}")
    print(f"  - 1960-1969: {counts['60s']}")
    print(f"  - 1970-1985: {counts['70s_85']}")
    print(f"File saved to {output_file}.")

if __name__ == "__main__":
    build_territory_map()