import requests
import streamlit as st
import folium
from folium.plugins import Fullscreen
from streamlit_folium import st_folium


PRIORITY_COLORS = {
    "Critical": "red",
    "High": "orange",
    "Medium": "blue",
    "Low": "green",
}


def fetch_route(start_lat, start_lon, end_lat, end_lon):
    """Return OSRM route geometry, distance and ETA."""
    try:
        url = (
            "https://router.project-osrm.org/route/v1/driving/"
            f"{start_lon},{start_lat};{end_lon},{end_lat}"
            "?overview=full&geometries=geojson"
        )

        response = requests.get(
            url,
            timeout=6
        )

        response.raise_for_status()

        data = response.json()

        route = data["routes"][0]

        return {
            "geometry": route["geometry"]["coordinates"],
            "distance_km": route["distance"] / 1000,
            "eta_minutes": route["duration"] / 60,
        }

    except Exception:
        return None


def reverse_geocode(lat, lon):
    """Return a human-readable address in English."""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"

        response = requests.get(
            url,
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "addressdetails": 1,
                "accept-language": "en",
            },
            headers={
                "User-Agent": "RescueLens-Emergency-App/1.0",
                "Accept-Language": "en",
            },
            timeout=6,
        )

        response.raise_for_status()

        data = response.json()

        return data.get("display_name")

    except Exception:
        return None


def render_map(reports, responders, selected=None):

    # Default location
    center = [29.3956, 71.6836]

    # Center map on selected emergency
    if selected:
        center = [
            selected["latitude"],
            selected["longitude"]
        ]

    # Center map on first report
    elif reports:
        center = [
            reports[0]["latitude"],
            reports[0]["longitude"]
        ]

    # Create map
    m = folium.Map(
        location=center,
        zoom_start=12,
        control_scale=True
    )

    # Add fullscreen button
    Fullscreen().add_to(m)

    # ==============================
    # ADD RESPONDERS
    # ==============================

    for responder in responders:

        folium.Marker(
            [
                responder["latitude"],
                responder["longitude"]
            ],

            tooltip=(
                f"{responder['name']} · "
                f"{responder['type']}"
            ),

            popup=(
                f"<b>{responder['name']}</b><br>"
                f"{responder['type']}<br>"
                f"Available: "
                f"{'Yes' if responder['available'] else 'No'}"
            ),

            icon=folium.Icon(
                color=(
                    "green"
                    if responder["available"]
                    else "gray"
                ),
                icon="user"
            ),

        ).add_to(m)

    # ==============================
    # ADD EMERGENCY REPORTS
    # ==============================

    for r in reports:

        color = PRIORITY_COLORS.get(
            r["priority"],
            "gray"
        )

        popup = (
            f"<b>#{r['display_number']} · "
            f"{r['priority']}</b><br>"

            f"{r['emergency_type']}<br>"

            f"{r['ai_summary'] or r['description'][:100]}<br>"

            f"Status: {r['status']}"
        )

        folium.Marker(
            [
                r["latitude"],
                r["longitude"]
            ],

            tooltip=(
                f"#{r['display_number']} · "
                f"{r['priority']}"
            ),

            popup=folium.Popup(
                popup,
                max_width=320
            ),

            icon=folium.Icon(
                color=color,
                icon="warning-sign"
            ),

        ).add_to(m)

        # ==============================
        # DRAW ROUTE TO SELECTED REPORT
        # ==============================

        assignment = r.get("assignment")

        if (
            assignment
            and selected
            and selected.get("id") == r.get("id")
        ):

            responder = next(
                (
                    x
                    for x in responders
                    if x["id"]
                    == assignment.get("responder_id")
                ),
                None
            )

            if responder:

                route = fetch_route(
                    responder["latitude"],
                    responder["longitude"],
                    r["latitude"],
                    r["longitude"],
                )

                if route:

                    # Convert GeoJSON coordinates
                    # [longitude, latitude]
                    # to Folium coordinates
                    # [latitude, longitude]

                    points = [
                        [lat, lon]
                        for lon, lat
                        in route["geometry"]
                    ]

                    folium.PolyLine(
                        points,
                        weight=5,
                        opacity=0.85,
                        tooltip="OSRM driving route"
                    ).add_to(m)

                    assignment["distance_km"] = (
                        route["distance_km"]
                    )

                    assignment["eta_minutes"] = (
                        route["eta_minutes"]
                    )

    # Display map in Streamlit

    st_folium(
        m,
        height=520,
        use_container_width=True,
        key="rescue_map"
    )