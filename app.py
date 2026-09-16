import os
from datetime import datetime, timezone
from io import BytesIO

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)

from ai_service import triage_emergency
from db import (
    init_db,
    create_emergency,
    list_emergencies,
    get_stats,
    seed_responders,
    list_responders,
    assign_responder,
    update_status,
)
from map_utils import render_map, reverse_geocode
from streamlit_js_eval import get_geolocation


load_dotenv()

st.set_page_config(
    page_title="RescueLens",
    page_icon="🚨",
    layout="wide",
)

init_db()
seed_responders()


def priority_rank(p):
    return {
        "Critical": 0,
        "High": 1,
        "Medium": 2,
        "Low": 3,
    }.get(p, 4)


# =============================================================
# PDF REPORT GENERATOR
# =============================================================

def generate_rescue_report_pdf(reports):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=20,
        leading=24,
        spaceAfter=6,
    )

    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=9,
        leading=12,
        spaceAfter=12,
    )

    cell_style = ParagraphStyle(
        "CellStyle",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
    )

    header_style = ParagraphStyle(
        "HeaderStyle",
        parent=cell_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
        alignment=TA_CENTER,
    )

    story = []

    # ---------------------------------------------------------
    # TITLE
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "RescueLens",
            title_style,
        )
    )

    story.append(
        Paragraph(
            "Government Rescue Service Report",
            subtitle_style,
        )
    )

    generated_time = datetime.now().strftime(
        "%d %B %Y, %I:%M %p"
    )

    story.append(
        Paragraph(
            f"Generated on: {generated_time}",
            cell_style,
        )
    )

    story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # SUMMARY STATISTICS
    # ---------------------------------------------------------

    total_cases = len(reports)

    total_people = sum(
        int(r.get("people_affected") or 0)
        for r in reports
    )

    critical_count = sum(
        r.get("priority") == "Critical"
        for r in reports
    )

    high_count = sum(
        r.get("priority") == "High"
        for r in reports
    )

    medium_count = sum(
        r.get("priority") == "Medium"
        for r in reports
    )

    low_count = sum(
        r.get("priority") == "Low"
        for r in reports
    )

    resolved_count = sum(
        r.get("status") == "Resolved"
        for r in reports
    )

    active_count = total_cases - resolved_count

    summary_data = [
        [
            "TOTAL CASES",
            "PEOPLE AFFECTED",
            "CRITICAL",
            "HIGH",
            "MEDIUM",
            "LOW",
            "ACTIVE",
            "RESOLVED",
        ],
        [
            str(total_cases),
            str(total_people),
            str(critical_count),
            str(high_count),
            str(medium_count),
            str(low_count),
            str(active_count),
            str(resolved_count),
        ],
    ]

    summary_table = Table(
        summary_data,
        colWidths=[
            65,
            90,
            60,
            55,
            65,
            55,
            60,
            65,
        ],
    )

    summary_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#1f2937"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "BACKGROUND",
                    (0, 1),
                    (-1, 1),
                    colors.HexColor("#f3f4f6"),
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold",
                ),
                (
                    "FONTNAME",
                    (0, 1),
                    (-1, 1),
                    "Helvetica-Bold",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER",
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    story.append(summary_table)

    story.append(Spacer(1, 18))

    # ---------------------------------------------------------
    # RECORDS TITLE
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Emergency Service Records",
            styles["Heading2"],
        )
    )

    story.append(Spacer(1, 8))

    # ---------------------------------------------------------
    # REPORT TABLE
    # ---------------------------------------------------------

    table_data = [
        [
            Paragraph("Emergency", header_style),
            Paragraph("Reporter", header_style),
            Paragraph("Location", header_style),
            Paragraph("People", header_style),
            Paragraph("Severity", header_style),
            Paragraph("Emergency Type", header_style),
            Paragraph("Rescue Team", header_style),
            Paragraph("Status", header_style),
            Paragraph("Date / Time", header_style),
        ]
    ]

    for r in reports:

        assignment = r.get("assignment") or {}

        responder_name = assignment.get(
            "responder_name",
            "Not assigned",
        )

        created_at = r.get("created_at") or ""

        if created_at:
            try:
                dt = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )

                created_at = dt.strftime(
                    "%d-%m-%Y %H:%M"
                )

            except Exception:
                pass

        table_data.append(
            [
                Paragraph(
                    f"#{r.get('display_number', '')}",
                    cell_style,
                ),

                Paragraph(
                    str(
                        r.get("reporter_name")
                        or "Anonymous"
                    ),
                    cell_style,
                ),

                Paragraph(
                    str(
                        r.get("location")
                        or "Not provided"
                    ),
                    cell_style,
                ),

                Paragraph(
                    str(
                        r.get("people_affected")
                        or 0
                    ),
                    cell_style,
                ),

                Paragraph(
                    str(
                        r.get("priority")
                        or "Unknown"
                    ),
                    cell_style,
                ),

                Paragraph(
                    str(
                        r.get("emergency_type")
                        or "Unknown"
                    ),
                    cell_style,
                ),

                Paragraph(
                    str(responder_name),
                    cell_style,
                ),

                Paragraph(
                    str(
                        r.get("status")
                        or "Unknown"
                    ),
                    cell_style,
                ),

                Paragraph(
                    str(created_at),
                    cell_style,
                ),
            ]
        )

    report_table = Table(
        table_data,
        repeatRows=1,
        colWidths=[
            55,
            75,
            90,
            45,
            55,
            75,
            90,
            80,
            80,
        ],
    )

    report_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#111827"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.grey,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (0, -1),
                    "CENTER",
                ),
                (
                    "ALIGN",
                    (3, 1),
                    (3, -1),
                    "CENTER",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
            ]
        )
    )

    story.append(report_table)

    story.append(Spacer(1, 15))

    story.append(
        Paragraph(
            "This report summarizes emergency cases and "
            "rescue response activity recorded by the "
            "RescueLens system.",
            cell_style,
        )
    )

    doc.build(story)

    buffer.seek(0)

    return buffer.getvalue()


# =============================================================
# MAIN APPLICATION
# =============================================================

def main():

    st.markdown(
        """
        <style>

        .block-container {
            padding-top: 3rem;
            padding-bottom: 2rem;
        }

        .brand {
            font-size: 2rem;
            font-weight: 800;
            letter-spacing: -0.04em;
            line-height: 1.1;
        }

        .brand span {
            color: #dc2626;
        }

        .sub {
            color: #6b7280;
            margin-top: -10px;
            margin-bottom: 10px;
        }

        .critical {
            border-left: 5px solid #dc2626;
            padding: 12px;
            background: rgba(220,38,38,.08);
        }

        .high {
            border-left: 5px solid #f59e0b;
            padding: 12px;
            background: rgba(245,158,11,.08);
        }

        .medium {
            border-left: 5px solid #eab308;
            padding: 12px;
            background: rgba(234,179,11,.08);
        }

        /* Compact emergency queue cards */
        [class*="st-key-queue_critical_"] {
            border: 2px solid #dc2626 !important;
            border-radius: 12px !important;
        }

        [class*="st-key-queue_normal_"] {
            border: 2px solid #16a34a !important;
            border-radius: 12px !important;
        }

        .queue-card-marker {
            display: none;
        }

        /* The queue itself: 3 cards per row on desktop. */
        @media (min-width: 901px) {
            div[data-testid="stHorizontalBlock"]:has(.queue-card-marker) {
                gap: 0.8rem !important;
            }
        }

        /* On narrow/mobile screens, keep two queue cards per row.
           This selector is scoped to the queue row only. */
        @media (max-width: 900px) {
            div[data-testid="stHorizontalBlock"]:has(.queue-card-marker) {
                flex-wrap: wrap !important;
                gap: 0.65rem !important;
            }

            div[data-testid="stHorizontalBlock"]:has(.queue-card-marker) > div[data-testid="stColumn"] {
                flex: 0 0 calc(50% - 0.35rem) !important;
                min-width: calc(50% - 0.35rem) !important;
                width: calc(50% - 0.35rem) !important;
            }
        }

        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
    '<div class="brand">RESCUE<span>LENS</span></div>',
    unsafe_allow_html=True,
)
    

    st.markdown(
        '<div class="sub">'
        'Generative-AI emergency report prioritization & coordination'
        '</div>',
        unsafe_allow_html=True,
    )

    command, citizen = st.tabs(
        [
            "COMMAND CENTER",
            "CITIZEN SOS",
        ]
    )

    # =========================================================
    # CITIZEN SOS
    # =========================================================

    with citizen:

        st.subheader("Report an Emergency")

        if "geo_status" not in st.session_state:
            st.session_state.geo_status = None
        if "geo_attempt" not in st.session_state:
            st.session_state.geo_attempt = 0

        detect_clicked = st.button(
            "📍 Use My Current Location",
            key="detect_location_btn",
        )

        if detect_clicked:
            st.session_state.geo_attempt += 1
            st.session_state.geo_status = "requesting"

        if st.session_state.geo_status == "requesting":

            with st.spinner("Requesting location permission..."):

                geo = get_geolocation(
                    component_key=f"rescuelens_geo_{st.session_state.geo_attempt}"
                )

            if geo is not None:

                if isinstance(geo, dict) and "error" in geo:

                    error_code = geo["error"].get("code")

                    if error_code == 1:
                        st.session_state.geo_status = "denied"
                    elif error_code == 2:
                        st.session_state.geo_status = "unavailable"
                    elif error_code == 3:
                        st.session_state.geo_status = "timeout"
                    else:
                        st.session_state.geo_status = "failed"

                elif isinstance(geo, dict) and "coords" in geo:

                    coords = geo["coords"]
                    st.session_state.detected_lat = coords["latitude"]
                    st.session_state.detected_lon = coords["longitude"]
                    st.session_state.detected_address = reverse_geocode(
                        coords["latitude"], coords["longitude"]
                    )
                    st.session_state.geo_status = "success"

        if st.session_state.geo_status == "success":
            st.success(
                "📍 Location detected automatically: "
                f"{st.session_state.get('detected_address') or (str(st.session_state.detected_lat) + ', ' + str(st.session_state.detected_lon))}"
            )
        elif st.session_state.geo_status == "denied":
            st.error(
                "Location permission was denied. Please allow location access "
                "in your browser settings to detect your location automatically, "
                "or enter your location manually below."
            )
        elif st.session_state.geo_status == "unavailable":
            st.warning(
                "Location services (GPS) appear to be disabled or unavailable. "
                "Please enable location services on your device, or enter your "
                "location manually below."
            )
        elif st.session_state.geo_status == "timeout":
            st.warning(
                "Location request timed out. Please try again, or enter your "
                "location manually below."
            )
        elif st.session_state.geo_status == "failed":
            st.warning(
                "Could not detect your location automatically. Please try again, "
                "or enter your location manually below."
            )

        with st.form(
            "sos_form",
            clear_on_submit=True,
        ):

            description = st.text_area(
                "Emergency description",
                placeholder=(
                    "Example: Flood water has entered our house. "
                    "Six people are trapped and one person is unconscious."
                ),
                height=140,
            )

            c1, c2 = st.columns(2)

            with c1:

                location = st.text_input(
                    "Location / address",
                    value=st.session_state.get("detected_address") or "",
                    placeholder="e.g. Bahawalpur, Punjab",
                )

                lat = st.number_input(
                    "Latitude",
                    value=st.session_state.get("detected_lat", 29.3956),
                    format="%.6f",
                )

            with c2:

                people = st.number_input(
                    "People affected",
                    min_value=1,
                    max_value=500,
                    value=1,
                )

                lon = st.number_input(
                    "Longitude",
                    value=st.session_state.get("detected_lon", 71.6836),
                    format="%.6f",
                )

            c3, c4 = st.columns(2)

            with c3:

                name = st.text_input(
                    "Reporter name (optional)"
                )

            with c4:

                phone = st.text_input(
                    "Reporter phone (optional)"
                )

            submitted = st.form_submit_button(
                "SEND EMERGENCY REPORT",
                type="primary",
                use_container_width=True,
            )

        if submitted:

            if len(description.strip()) < 10:

                st.error(
                    "Please provide a more detailed emergency description."
                )

            else:

                with st.spinner(
                    "Analyzing emergency with Generative AI..."
                ):

                    triage = triage_emergency(
                        description,
                        int(people),
                    )

                emergency = create_emergency(
                    description=description.strip(),
                    location=location.strip(),
                    latitude=float(lat),
                    longitude=float(lon),
                    people_affected=int(people),
                    reporter_name=name.strip() or None,
                    reporter_phone=phone.strip() or None,
                    triage=triage,
                )

                st.success(
                    f"Emergency #{emergency['display_number']} submitted."
                )

                st.info(
                    f"AI result: **{triage['emergency_type']}** · "
                    f"**{triage['priority']}** · "
                    f"{triage['required_team']}"
                )

                st.write(
                    triage["summary"]
                )

    # =========================================================
    # COMMAND CENTER
    # =========================================================

    with command:

        st.subheader(
            "Emergency Command Center"
        )

        stats = get_stats()

        a, b, c, d, e = st.columns(5)

        a.metric(
            "Total",
            stats["total"],
        )

        b.metric(
            "Critical",
            stats["critical"],
        )

        c.metric(
            "High",
            stats["high"],
        )

        d.metric(
            "Medium",
            stats["medium"],
        )

        e.metric(
            "Resolved",
            stats["resolved"],
        )

        st.divider()

        # =====================================================
        # DATA
        # =====================================================

        reports_all = list_emergencies()
        responders = list_responders()

        # =====================================================
        # PRIORITY QUEUE
        # =====================================================

        st.markdown("### Priority Queue")

        filter_value = st.selectbox(
            "Filter",
            [
                "All",
                "Critical",
                "High",
                "Medium",
                "Low",
                "Resolved",
            ],
            key="queue_filter",
        )

        reports = sorted(
            reports_all,
            key=lambda x: (
                priority_rank(x["priority"]),
                x["created_at"],
            ),
        )

        if filter_value != "All":
            reports = [
                r
                for r in reports
                if r["priority"] == filter_value
                or r["status"] == filter_value
            ]

        if not reports:
            st.info("No reports found.")
        else:
            # Marker lets the responsive CSS target ONLY this row.
            queue_columns = st.columns(3)
            for i, r in enumerate(reports):
                col = queue_columns[i % 3]
                with col:
                    priority = str(r.get("priority") or "Medium").lower()
                    card_class = "critical" if priority == "critical" else "normal"

                    with st.container(
                        border=True,
                        key=f"queue_{card_class}_{r['id']}",
                    ):
                        st.markdown(
                            f'<span class="queue-card-marker {card_class}"></span>',
                            unsafe_allow_html=True,
                        )

                        st.markdown(
                            f"**#{r['display_number']} · {r['priority']}**"
                        )

                        st.caption(
                            f"{r['emergency_type']} · {r['status']}"
                        )

                        summary = (
                            r.get("ai_summary")
                            or r.get("description", "")[:150]
                        )
                        st.write(summary[:180])

                        if st.button(
                            "View",
                            key=f"view_{r['id']}",
                            use_container_width=True,
                        ):
                            st.session_state["selected_id"] = r["id"]
                            st.rerun()

        st.divider()

        # =========================================================
        # LIVE DISASTER MAP
        # =========================================================

        st.markdown("### Live Disaster Map")
        st.caption(
            "Active emergency locations and responder positions. "
            "Select a report from the queue to inspect its details."
        )

        selected_id = st.session_state.get("selected_id")

        selected = next(
            (r for r in reports_all if r["id"] == selected_id),
            None,
        )

        render_map(
            reports_all,
            responders,
            selected,
        )

        st.divider()

        # =========================================================
        # SELECTED EMERGENCY REPORT
        # =========================================================

        if selected:

            st.markdown(
                f"### Emergency #{selected['display_number']}"
            )

            x1, x2, x3 = st.columns(3)

            x1.metric("Priority", selected["priority"])
            x2.metric("Type", selected["emergency_type"])
            x3.metric("People", selected["people_affected"])

            st.markdown("**AI Summary**")
            st.info(
                selected["ai_summary"]
                or "No AI summary available."
            )

            st.markdown("**Extracted Information**")

            q1, q2, q3, q4 = st.columns(4)

            q1.write(
                f"Trapped: "
                f"{'Yes' if selected['people_trapped'] else 'No'}"
            )
            q2.write(
                f"Medical: "
                f"{'Yes' if selected['medical_emergency'] else 'No'}"
            )
            q3.write(
                f"Critical injury: "
                f"{'Yes' if selected['critical_injury'] else 'No'}"
            )
            q4.write(
                f"Team: {selected['required_team']}"
            )

            st.markdown("**Citizen report**")
            st.write(selected["description"])

            st.caption(
                f"Location: "
                f"{selected['location'] or 'Not provided'} · "
                f"{selected['latitude']:.5f}, "
                f"{selected['longitude']:.5f}"
            )

            # =====================================================
            # RESPONSE STATUS
            # =====================================================

            st.markdown("**Response status**")

            statuses = [
                "Waiting for responder",
                "Dispatched",
                "In Progress",
                "Resolved",
            ]

            current_index = (
                statuses.index(selected["status"])
                if selected["status"] in statuses
                else 0
            )

            new_status = st.selectbox(
                "Status",
                statuses,
                index=current_index,
                key=f"status_{selected['id']}",
            )

            if st.button(
                "UPDATE STATUS",
                key=f"status_btn_{selected['id']}",
            ):
                update_status(selected["id"], new_status)
                st.success("Status updated.")
                st.rerun()

            # =====================================================
            # RESPONDER ASSIGNMENT
            # =====================================================

            if selected["status"] != "Resolved":

                st.markdown("**Responder assignment**")

                available = [
                    x
                    for x in responders
                    if int(x.get("available", 0)) == 1
                ]

                # Only available responders from the AI-required team
                # are offered. For example, a Fire emergency only shows
                # available Fire Teams. A resolved task releases that
                # responder in db.update_status(), making it selectable
                # for the next emergency.
                assignment_pool = [
                    x
                    for x in available
                    if x["type"] == selected["required_team"]
                ]

                if assignment_pool:
                    options = {
                        f"{x['name']} · {x['type']}": x["id"]
                        for x in assignment_pool
                    }

                    chosen = st.selectbox(
                        "Responder",
                        list(options.keys()),
                        key=f"resp_{selected['id']}",
                    )

                    if st.button(
                        "ASSIGN RESPONDER",
                        key=f"assign_{selected['id']}",
                    ):
                        result = assign_responder(
                            selected["id"],
                            options[chosen],
                        )

                        if result["ok"]:
                            st.success(
                                f"Assigned "
                                f"{result['responder']['name']} · "
                                f"{result['distance_km']:.1f} km · ETA "
                                f"{result['eta_minutes']:.0f} min"
                            )
                            st.rerun()
                        else:
                            st.error(result["error"])
                else:
                    st.warning(
                        f"No available {selected['required_team']} found. "
                        "The team will appear here when one becomes available."
                    )

            # =====================================================
            # EXISTING ASSIGNMENT
            # =====================================================

            if selected.get("assignment"):
                ass = selected["assignment"]

                st.success(
                    f"Assigned: {ass['responder_name']} · "
                    f"{ass['distance_km']:.1f} km · ETA "
                    f"{ass['eta_minutes']:.0f} min"
                )

        else:
            st.info(
                "Select an emergency from the Priority Queue to inspect "
                "its AI analysis, responder assignment, and status."
            )

        # =========================================================
        # GOVERNMENT RESCUE REPORT
        # =========================================================

        st.divider()

        with st.expander(
            "GOVERNMENT RESCUE REPORT",
            expanded=False,
        ):

            st.markdown(
                "### Rescue Service Report"
            )

            st.caption(
                "Generate a complete record of rescue "
                "operations recorded in RescueLens."
            )

            # -----------------------------------------------------
            # REPORT DATA
            # -----------------------------------------------------

            report_data = []

            for r in reports_all:

                assignment = (
                    r.get("assignment")
                    or {}
                )

                responder_name = assignment.get(
                    "responder_name",
                    "Not assigned",
                )

                created_at = (
                    r.get("created_at")
                    or ""
                )

                if created_at:

                    try:

                        dt = datetime.fromisoformat(
                            created_at.replace(
                                "Z",
                                "+00:00",
                            )
                        )

                        created_at = dt.strftime(
                            "%d-%m-%Y %H:%M"
                        )

                    except Exception:

                        pass

                report_data.append(
                    {
                        "Emergency": (
                            f"#{r.get('display_number', '')}"
                        ),
                        "Reporter": (
                            r.get("reporter_name")
                            or "Anonymous"
                        ),
                        "Location": (
                            r.get("location")
                            or "Not provided"
                        ),
                        "People Affected": (
                            r.get("people_affected")
                            or 0
                        ),
                        "Severity": (
                            r.get("priority")
                            or "Unknown"
                        ),
                        "Emergency Type": (
                            r.get("emergency_type")
                            or "Unknown"
                        ),
                        "Rescue Team": (
                            responder_name
                        ),
                        "Status": (
                            r.get("status")
                            or "Unknown"
                        ),
                        "Date / Time": (
                            created_at
                        ),
                    }
                )

            # -----------------------------------------------------
            # SHOW REPORT
            # -----------------------------------------------------

            if report_data:

                df_report = pd.DataFrame(
                    report_data
                )

                total_people_report = int(
                    df_report[
                        "People Affected"
                    ].sum()
                )

                resolved_report = int(
                    (
                        df_report["Status"]
                        == "Resolved"
                    ).sum()
                )

                active_report = int(
                    (
                        df_report["Status"]
                        != "Resolved"
                    ).sum()
                )

                rc1, rc2, rc3, rc4 = st.columns(4)

                rc1.metric(
                    "Total Cases",
                    len(df_report),
                )

                rc2.metric(
                    "People Affected",
                    total_people_report,
                )

                rc3.metric(
                    "Resolved",
                    resolved_report,
                )

                rc4.metric(
                    "Active Cases",
                    active_report,
                )

                st.markdown(
                    "#### Emergency Records"
                )

                st.dataframe(
                    df_report,
                    use_container_width=True,
                    hide_index=True,
                )

                # -------------------------------------------------
                # PDF DOWNLOAD
                # -------------------------------------------------

                pdf_data = (
                    generate_rescue_report_pdf(
                        reports_all
                    )
                )

                st.download_button(
                    label="DOWNLOAD PDF REPORT",
                    data=pdf_data,
                    file_name=(
                        "RescueLens_Government_"
                        "Rescue_Report.pdf"
                    ),
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )

            else:

                st.info(
                    "No emergency records are available "
                    "to generate a report."
                )


if __name__ == "__main__":
    main()
