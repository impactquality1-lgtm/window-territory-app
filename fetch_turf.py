import json
import urllib.request
import urllib.parse
import sys

# Ask for any 5-digit ZIP code in Hennepin, Ramsey, or surrounding Twin Cities metro
zip_code = input("Enter any 5-digit ZIP code (e.g. 55428, 55104, 55410, 55113): ").strip()

if not zip_code.isdigit() or len(zip_code) != 5:
    print("❌ Invalid input: Please enter a valid 5-digit numeric ZIP code.")
    sys.exit(1)

print(f"🔍 Geocoding spatial boundaries for ZIP {zip_code}...")

# 1. Resolve exact bounding box for the ZIP using Nominatim
nominatim_url = f"https://nominatim.openstreetmap.org/search?postalcode={zip_code}&country=USA&state=Minnesota&format=json"
req = urllib.request.Request(nominatim_url, headers={"User-Agent": "CanvassTurfTool/1.0"})

try:
    with urllib.request.urlopen(req) as resp:
        geo_data = json.loads(resp.read().decode("utf-8"))
        if not geo_data:
            print(f"❌ ZIP code {zip_code} could not be geocoded. Verify the number.")
            sys.exit(1)
            
        bbox = geo_data[0]['boundingbox']
        min_lat, max_lat = float(bbox[0]), float(bbox[1])
        min_lng, max_lng = float(bbox[2]), float(bbox[3])
        print(f"📍 Found ZIP Bounds: [{min_lat}, {min_lng}] to [{max_lat}, {max_lng}]")

except Exception as e:
    print("❌ Geocoding error:", e)
    sys.exit(1)

# 2. Query Met Council FeatureServer (Layer 3 = Hennepin County, Layer 6 = Ramsey County)
# By default, Layer 3 serves Hennepin. We test Layer 3 and Layer 6 if necessary.
base_urls = [
    "https://arcgis.metc.state.mn.us/data1/rest/services/parcels/Parcels/FeatureServer/3/query", # Hennepin
    "https://arcgis.metc.state.mn.us/data1/rest/services/parcels/Parcels/FeatureServer/6/query"  # Ramsey
]

GRID_SIZE = 4
lat_step = (max_lat - min_lat) / GRID_SIZE
lng_step = (max_lng - min_lng) / GRID_SIZE

all_features = []
seen_pids = set()

print(f"🌐 Subdividing boundary into {GRID_SIZE*GRID_SIZE} spatial tiles to bypass server limits...")

for base_url in base_urls:
    county_name = "Hennepin" if "/3/" in base_url else "Ramsey"
    
    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            tile_min_lat = min_lat + (row * lat_step)
            tile_max_lat = tile_min_lat + lat_step
            tile_min_lng = min_lng + (col * lng_step)
            tile_max_lng = tile_min_lng + lng_step

            params = {
                'where': '1=1',
                'geometry': f"{tile_min_lng},{tile_min_lat},{tile_max_lng},{tile_max_lat}",
                'geometryType': 'esriGeometryEnvelope',
                'spatialRel': 'esriSpatialRelIntersects',
                'inSR': '4326',
                'outFields': '*',
                'outSR': '4326',
                'f': 'json',
                'resultRecordCount': '2000'
            }

            query_string = urllib.parse.urlencode(params)
            full_url = f"{base_url}?{query_string}"

            gis_req = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})

            try:
                with urllib.request.urlopen(gis_req) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    features = data.get('features', [])
                    
                    for feat in features:
                        attrs = feat.get('attributes', {})
                        pid = attrs.get('OBJECTID') or attrs.get('PIN') or attrs.get('PID')
                        
                        if pid and pid in seen_pids:
                            continue
                        if pid:
                            seen_pids.add(pid)

                        geom = feat.get('geometry', {})
                        if 'rings' in geom and len(geom['rings']) > 0:
                            pts = geom['rings'][0]
                            feat['geometry']['x'] = sum([p[0] for p in pts]) / len(pts)
                            feat['geometry']['y'] = sum([p[1] for p in pts]) / len(pts)

                        all_features.append(feat)

            except Exception as e:
                pass

print(f"✅ Complete! Retrieved {len(all_features)} unique parcels for ZIP {zip_code}.")

output_data = {
    "type": "FeatureCollection",
    "features": all_features
}

with open("turf_data.js", "w") as f:
    f.write(f"window.CURRENT_ZIP = '{zip_code}';\n")
    f.write("window.TURF_DATA = " + json.dumps(output_data) + ";")

print("💾 Saved turf_data.js successfully!")