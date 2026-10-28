import json
import urllib.request
import folium
from folium.plugins import HeatMap

# 1. Minneapolis Open Data ArcGIS Feature Layer for Active CCS Permits
PERMIT_API_URL = (
    "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/CCS_Permits/FeatureServer/0/query"
    "?where=1%3D1&outFields=*&outSR=4326&f=json&resultRecordCount=1000"
)

# 2. Hennepin County Property Assessment Open Data (Sample Parcel API Endpoint for Year Built)
PARCEL_API_URL = (
    "https://services1.arcgis.com/123456/arcgis/rest/services/Hennepin_Parcels/FeatureServer/0/query"
    "?where=YEARBUILT%20%3E%3D%201950%20AND%20YEARBUILT%20%3C%3D%201985&outFields=OBJECTID,Display,YEARBUILT,Address&outSR=4326&f=json&resultRecordCount=500"
)

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("features", [])
    except Exception as e:
        print(f"Error fetching data from {url}: {e}")
        return []

def build_territory_map():
    print("Fetching active window permit data...")
    permit_features = fetch_json(PERMIT_API_URL)
    
    # Center map on Minneapolis using Esri World Street Map tiles
    m = folium.Map(
        location=[44.9778, -93.2650], 
        zoom_start=12,
        tiles="Esri.WorldStreetMap"
    )
    
    # Feature Groups for Layer Toggle Controls
    permit_group = folium.FeatureGroup(name="Active Window Permits (Competitor Activity)").add_to(m)
    age_group = folium.FeatureGroup(name="Target Homes (Built 1950-1985)").add_to(m)
    
    heat_data = []
    mapped_permits = 0

    # Process Active Window Permits
    for item in permit_features:
        attrs = item.get("attributes", {})
        geometry = item.get("geometry", {})
        
        lng = geometry.get("x")
        lat = geometry.get("y")
        
        if not lat or not lng:
            continue

        blob = " ".join([str(v) for v in attrs.values() if v is not None]).lower()
        
        if "window" in blob:
            heat_data.append([lat, lng])
            
            permit_no = attrs.get("permitNumber") or attrs.get("PermitNumber") or attrs.get("OBJECTID") or "N/A"
            address = attrs.get("Display") or attrs.get("Address") or "Minneapolis Location"
            contractor = attrs.get("applicantName") or attrs.get("ContractorName") or "Unknown Contractor"
            status = attrs.get("status") or attrs.get("Status") or "Active"
            description = attrs.get("comments") or attrs.get("Description") or "Window Replacement"

            popup_html = f"""
            <div style="font-family: sans-serif; font-size: 13px;">
                <b style="color: #b91c1c;">ACTIVE PERMIT</b><br>
                <b>Permit ID:</b> {permit_no}<br>
                <b>Status:</b> {status}<br>
                <b>Address:</b> {address}<br>
                <b>Contractor:</b> {contractor}<br>
                <b>Details:</b> {description}
            </div>
            """
            
            folium.CircleMarker(
                location=[lat, lng],
                radius=6,
                color="#b91c1c",
                fill=True,
                fill_color="#ef4444",
                fill_opacity=0.9,
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(permit_group)
            
            mapped_permits += 1

    # Add HeatMap to Permit Layer
    if heat_data:
        HeatMap(heat_data, radius=15, blur=10, max_zoom=15).add_to(permit_group)

    # Layer Control toggle on the top right
    folium.LayerControl(collapsed=False).add_to(m)

    output_file = "window_sales_map.html"
    m.save(output_file)
    print(f"\n--- MAP SUMMARY ---")
    print(f"Mapped {mapped_permits} active window permits to {output_file}.")

if __name__ == "__main__":
    build_territory_map()