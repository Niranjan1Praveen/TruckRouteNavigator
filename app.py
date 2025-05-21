import os
from flask import Flask
import folium
from supabase import create_client
from math import radians, cos, sin, sqrt, atan2
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Haversine formula to calculate distance in km between two lat/lon points
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

@app.route("/")
def map_view():
    # Default map center (India), will be overridden if user location is found
    map_center = [20.5937, 78.9629]
    zoom_level = 5

    # Fetch the user with the latest timestamp from VoiceResponse table
    voice_responses = supabase.table("VoiceResponse").select("*").order("createdAt", desc=True).limit(1).execute().data or []

    # Extract current user location (latest user based on timestamp)
    current_user_lat = current_user_lon = None
    if voice_responses:
        current_user = voice_responses[0]  # Latest user based on createdAt timestamp
        current_user_lat = current_user.get("Latitude")
        current_user_lon = current_user.get("Longitude")

        # If user location is found, center and zoom the map on the user
        if current_user_lat is not None and current_user_lon is not None:
            map_center = [current_user_lat, current_user_lon]
            zoom_level = 12  # Zoom in closer to the user's location

    # Create the map with the adjusted center and zoom
    m = folium.Map(location=map_center, zoom_start=zoom_level)

    # Mark the user with the latest timestamp on the map
    if current_user_lat is not None and current_user_lon is not None:
        folium.Marker(
            location=[current_user_lat, current_user_lon],
            popup="👤 User (Latest Timestamp)",
            icon=folium.Icon(color="blue", icon="user", prefix="fa")
        ).add_to(m)

    # Fetch trucks data
    trucks = supabase.table("Truck").select("*").execute().data or []

    # Find nearest truck to the latest user and calculate distance
    nearest_truck = None
    min_distance = float("inf")
    distance_km = None
    time_minutes = None
    nearest_truck_lat = nearest_truck_lon = None

    if current_user_lat is not None and current_user_lon is not None:
        for truck in trucks:
            lat = truck.get("Latitude")
            lon = truck.get("Longitude")
            if lat is None or lon is None:
                continue
            distance = haversine(current_user_lat, current_user_lon, lat, lon)
            if distance < min_distance:
                min_distance = distance
                nearest_truck = truck
                nearest_truck_lat = lat
                nearest_truck_lon = lon

    # Calculate distance and time for the legend if a nearest truck is found
    if nearest_truck and current_user_lat is not None and current_user_lon is not None:
        distance_km = min_distance
        truck_speed_kmh = 40  # Average speed in km/h
        time_hours = distance_km / truck_speed_kmh
        time_minutes = time_hours * 60  # Convert hours to minutes

    # Add all trucks markers
    for truck in trucks:
        lat = truck.get("Latitude")
        lon = truck.get("Longitude")
        name = truck.get("TruckDriverName", "Unnamed Truck")
        if lat is None or lon is None:
            continue

        is_nearest = nearest_truck and truck.get("id") == nearest_truck.get("id")
        color = "red" if is_nearest else "green"
        icon = "star" if is_nearest else "truck"

        # Add a dotted line between the user and the nearest truck
        if is_nearest:
            folium.PolyLine(
                locations=[[current_user_lat, current_user_lon], [lat, lon]],
                color="blue",
                weight=2.5,
                dash_array="5, 10"  # Creates a dotted line
            ).add_to(m)

        # Add the marker, and for the nearest truck, store its Leaflet ID for animation
        marker = folium.Marker(
            location=[lat, lon],
            popup=f"🚛 {'Nearest Truck: ' if is_nearest else ''}{name}",
            icon=folium.Icon(color=color, icon=icon, prefix="fa")
        ).add_to(m)

        # Store the Leaflet marker ID for the nearest truck
        if is_nearest:
            nearest_truck_marker_id = marker._id

    # Add animation for the nearest truck if it exists
    if nearest_truck and current_user_lat is not None and current_user_lon is not None:
        # Calculate a point slightly closer to the user (move 10% of the distance toward the user)
        delta_lat = (current_user_lat - nearest_truck_lat) * 0.1
        delta_lon = (current_user_lon - nearest_truck_lon) * 0.1
        intermediate_lat = nearest_truck_lat + delta_lat
        intermediate_lon = nearest_truck_lon + delta_lon

        # JavaScript to animate the nearest truck marker
        animation_js = f"""
        <script>
        document.addEventListener("DOMContentLoaded", function() {{
            var map = window._folium_map;
            var marker = null;

            // Find the marker by its Leaflet ID
            map.eachLayer(function(layer) {{
                if (layer._leaflet_id === "{nearest_truck_marker_id}") {{
                    marker = layer;
                }}
            }});

            if (marker) {{
                var originalPos = L.latLng({nearest_truck_lat}, {nearest_truck_lon});
                var intermediatePos = L.latLng({intermediate_lat}, {intermediate_lon});
                var movingForward = true;
                var progress = 0;
                var speed = 0.005;  // Slower speed for smooth animation

                function animateMarker() {{
                    if (movingForward) {{
                        progress += speed;
                        if (progress >= 1) {{
                            progress = 1;
                            movingForward = false;
                        }}
                    }} else {{
                        progress -= speed;
                        if (progress <= 0) {{
                            progress = 0;
                            movingForward = true;
                        }}
                    }}

                    // Interpolate between original and intermediate positions
                    var lat = originalPos.lat + (intermediatePos.lat - originalPos.lat) * progress;
                    var lng = originalPos.lng + (intermediatePos.lng - originalPos.lng) * progress;
                    marker.setLatLng([lat, lng]);

                    requestAnimationFrame(animateMarker);
                }}

                // Start the animation
                animateMarker();
            }}
        }});
        </script>
        """
        m.get_root().html.add_child(folium.Element(animation_js))

    # Add a custom legend in the top-right corner with distance and time
    legend_html = """
    <div style="
        position: fixed;
        top: 10px;
        right: 10px;
        z-index: 1000;
        background-color: white;
        padding: 10px;
        border: 2px solid black;
        border-radius: 5px;
        font-size: 14px;
        font-family: Arial, sans-serif;">
        <b>Nearest Truck Info</b><br>
    """
    if distance_km is not None and time_minutes is not None:
        legend_html += f"Distance: {distance_km:.2f} km<br>Est. Time: {time_minutes:.1f} minutes"
    else:
        legend_html += "No nearest truck found"
    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))

    return m._repr_html_()

if __name__ == "__main__":
    app.run(debug=True)