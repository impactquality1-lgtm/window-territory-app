import json
import urllib.request
import folium
from folium.plugins import HeatMap

# Minneapolis Open Data ArcGIS Feature Layer for CCS Permits
PERMIT_API_URL = (
    "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/CCS_Permits/FeatureServer/0/query"
    "?where=1%3D1&outFields=*&outSR=4326&f=json&resultRecordCount=1000"
)

def get_attr(attrs, *keys):
    """Case-insensitive attribute lookup."""
    lower_map = {str(k).lower(): v for k, v in attrs.items()}
    for key in keys:
        val = lower_map.get(key.lower())
        if val is not None and val != "":
            return val
    return None

def fetch_permits():
    print("Fetching permit data from Minneapolis Open Data API...")
    req = urllib.request.Request(PERMIT_API_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            features = data.get("features", [])
            print(f"Successfully connected! Retrieved {len(features)} raw permit features.")
            return features
    except Exception as e:
        print(f"Error fetching permit data: {e}")
        return []

def build_territory_map():
    features = fetch_permits()
    if not features:
        print("No features returned. Exiting map generation.")
        return

    # Center map on Minneapolis using Esri World Street Map tiles (bypasses local file 403 blocks)
    m = folium.Map(
        location=[44.9778, -93.2650], 
        zoom_start=12,
        tiles="Esri.WorldStreetMap"
    )
    
    heat_data = []
    mapped_count = 0

    for item in features:
        attrs = item.get("attributes", {})
        geometry = item.get("geometry", {})
        
        lng = geometry.get("x")
        lat = geometry.get("y")
        
        if not lat or not lng:
            continue

        desc = str(get_attr(attrs, "Description", "permitDescription", "workdescription", "permit_type", "folder_type") or "").lower()
        work_type = str(get_attr(attrs, "WorkType", "work_type", "permitTypeDesc") or "").lower()
        
        combined_text = f"{desc} {work_type}"
        
        if any(kw in combined_text for kw in ["window", "siding", "replace", "remodel", "renovation", "building", "residential"]):
            heat_data.append([lat, lng])
            
            permit_no = get_attr(attrs, "PermitNumber", "permitNumber", "permit_number", "folder_rsn", "objectid") or "N/A"
            address = get_attr(attrs, "Address", "siteAddress", "original_address", "street_address") or "Minneapolis Address"
            contractor = get_attr(attrs, "ContractorName", "contractor_name", "applicantName", "applicant_name") or "Unknown Contractor"
            
            popup_html = f"""
            <b>Permit:</b> {permit_no}<br>
            <b>Address:</b> {address}<br>
            <b>Contractor:</b> {contractor}<br>
            <b>Details:</b> {get_attr(attrs, 'Description', 'permitDescription') or 'N/A'}
            """
            
            folium.CircleMarker(
                location=[lat, lng],
                radius=4,
                color="#1d4ed8",
                fill=True,
                fill_color="#3b82f6",
                fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(m)
            
            mapped_count += 1

    if heat_data:
        HeatMap(heat_data, radius=15, blur=10, max_zoom=15).add_to(m)

    output_file = "window_sales_map.html"
    m.save(output_file)
    print(f"Successfully mapped {mapped_count} targeted permits to {output_file}.")

if __name__ == "__main__":
    build_territory_map()