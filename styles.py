"""styles.py — HTML-free, native Streamlit UI components.

This module previously existed but was missing from the project, which
is why `from styles import ...` in app.py raised ModuleNotFoundError.

Nothing here injects raw HTML/CSS — theming comes from
.streamlit/config.toml, exactly like the rest of this project.
"""
import streamlit as st

from recommendation_engine import star_rating, why_recommended
from utils import format_experience, format_location, format_salary, get_job_key


# =====================================================================
# METRIC CARDS
# =====================================================================

def render_metric_cards(total_jobs: int, companies: int, pages: int, current_page: int):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        with st.container(border=True):
            st.metric("💼 Total Jobs", total_jobs)
    with col2:
        with st.container(border=True):
            st.metric("🏢 Total Companies", companies)
    with col3:
        with st.container(border=True):
            st.metric("📄 Total Pages", pages)
    with col4:
        with st.container(border=True):
            st.metric("📍 Current Page", current_page)


def render_ai_metric_cards(avg_match: int, remote_count: int, internship_count: int,
                            fresher_count: int, last_updated_label: str):
    """Second row of metrics summarizing the AI ranking pass."""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        with st.container(border=True):
            st.metric("🎯 Avg. Match Score", f"{avg_match}%")
    with col2:
        with st.container(border=True):
            st.metric("🌐 Remote Jobs", remote_count)
    with col3:
        with st.container(border=True):
            st.metric("🎓 Internships", internship_count)
    with col4:
        with st.container(border=True):
            st.metric("🌱 Fresher-Friendly", fresher_count)
    st.caption(f"Results last updated: {last_updated_label}")


# =====================================================================
# JOB CARD
# =====================================================================

def render_job_card(job: dict, bookmarked: bool, on_toggle_bookmark, role: str = "",
                     wanted_skills: list = None, remote_only: bool = False,
                     experience_filter: str = "Any Experience", locations: list = None):
    """Render one job as a native Streamlit card.

    Shows the summary (title, company, location, salary, match score,
    "why recommended") up front; full description, skills, and
    highlights (Qualifications / Responsibilities / Benefits) live
    behind a "View Details" expander so the list stays scannable.

    `on_toggle_bookmark(job)` is called when the Save button is
    pressed; the caller owns the actual bookmark storage.
    """
    wanted_skills = wanted_skills or []
    locations = locations or []

    title = job.get("job_title", "Not Available")
    company = job.get("employer_name", "Not Available")
    logo = job.get("employer_logo")
    job_employment = job.get("job_employment_type", "Not Available")
    publisher = job.get("job_publisher", "Not Available")
    posted = job.get("job_posted_at_datetime_utc", "")
    apply_link = job.get("job_apply_link")
    description = job.get("job_description", "No Description Available")
    is_remote = job.get("job_is_remote")
    skills = job.get("_skills", [])
    match_score = job.get("_match_score")

    if is_remote is True:
        remote_text = "🌐 Remote"
    elif is_remote is False:
        remote_text = "🏢 On-site"
    else:
        remote_text = "🌐 Remote: Not specified"

    with st.container(border=True):
        logo_col, info_col, action_col = st.columns([1, 5, 1.4])

        with logo_col:
            if logo:
                st.image(logo, width=56)
            else:
                st.write("🏢")

        with info_col:
            st.subheader(title)
            st.caption(f"🏢 {company}")

            if match_score is not None:
                st.caption(star_rating(match_score) + f" — {match_score}% match")

            row1_col1, row1_col2, row1_col3 = st.columns(3)
            row1_col1.write(f"📍 {format_location(job)}")
            row1_col2.write(f"💼 {job_employment}")
            row1_col3.write(f"💰 {format_salary(job)}")

            row2_col1, row2_col2, row2_col3 = st.columns(3)
            row2_col1.write(f"🎯 {format_experience(job)}")
            row2_col2.write(remote_text)
            if posted:
                row2_col3.write(f"📅 {posted[:10]}")

            if skills:
                st.caption("🏷️ " + " · ".join(skills[:8]))

            st.caption(f"Publisher: {publisher}")

        with action_col:
            if apply_link:
                st.link_button("Apply ➜", apply_link, use_container_width=True)

            bookmark_label = "★ Saved" if bookmarked else "☆ Save Job"
            if st.button(
                bookmark_label,
                key=f"bookmark_btn_{get_job_key(job)}",
                use_container_width=True,
            ):
                on_toggle_bookmark(job)
                st.rerun()

        with st.expander("🔎 View Details"):
            reasons = why_recommended(job, role, wanted_skills, remote_only, experience_filter, locations)
            if reasons:
                st.markdown("**Why recommended:**")
                for reason in reasons:
                    st.caption(reason)
                st.divider()

            desc_tab, highlights_tab, share_tab = st.tabs(
                ["📄 Description", "📋 Highlights", "🔗 Share"]
            )
            with desc_tab:
                st.write(description)

            with highlights_tab:
                highlights = job.get("job_highlights") or {}
                qualifications = highlights.get("Qualifications") or []
                responsibilities = highlights.get("Responsibilities") or []
                benefits = highlights.get("Benefits") or []

                if qualifications:
                    st.markdown("**Qualifications**")
                    for item in qualifications:
                        st.caption(f"• {item}")
                if responsibilities:
                    st.markdown("**Responsibilities**")
                    for item in responsibilities:
                        st.caption(f"• {item}")
                if benefits:
                    st.markdown("**Benefits**")
                    for item in benefits:
                        st.caption(f"• {item}")
                if not (qualifications or responsibilities or benefits):
                    st.caption("No additional highlights provided for this listing.")

            with share_tab:
                if apply_link:
                    st.caption("Copy this link to share the job:")
                    st.code(apply_link, language=None)
                else:
                    st.caption("No apply link available to share.")


# =====================================================================
# PAGINATION CONTROLS
# =====================================================================

def render_pagination_controls(current_page: int, pages_count: int, range_start: int,
                                range_end: int, total_jobs: int, jump_to_page=None):
    """Renders Previous / page info / Next, plus an optional "jump to
    page" number input when `jump_to_page(page_number)` is provided.
    Returns (prev_clicked, next_clicked).
    """
    st.divider()
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        prev_clicked = st.button(
            "⬅ Previous", use_container_width=True, disabled=current_page <= 1
        )

    with col2:
        st.write(f"Page {current_page} of {max(pages_count, 1)}")
        st.caption(f"Showing Jobs {range_start}\u2013{range_end} of {total_jobs}")

    with col3:
        next_clicked = st.button(
            "Next ➜", use_container_width=True, disabled=current_page >= pages_count
        )

    if jump_to_page is not None and pages_count > 1:
        jump_col1, jump_col2 = st.columns([3, 1])
        with jump_col1:
            target_page = st.number_input(
                "Jump to page", min_value=1, max_value=max(pages_count, 1),
                value=current_page, step=1, label_visibility="collapsed",
            )
        with jump_col2:
            if st.button("Go", use_container_width=True):
                jump_to_page(target_page)

    return prev_clicked, next_clicked