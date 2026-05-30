"""Streamlit theme injection."""

from __future__ import annotations

import streamlit as st


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --eve-bg: #05080d;
            --eve-surface: #08111b;
            --eve-surface-2: #0c1722;
            --eve-panel: rgba(9, 18, 29, 0.94);
            --eve-panel-2: rgba(12, 25, 38, 0.9);
            --eve-border: rgba(125, 211, 252, 0.18);
            --eve-border-strong: rgba(34, 211, 238, 0.42);
            --eve-text: #e5edf7;
            --eve-muted: #91a4b8;
            --eve-cyan: #28d4e8;
            --eve-green: #35d35f;
            --eve-red: #f25f5c;
            --eve-amber: #e5b84b;
            --eve-purple: #a78bfa;
        }

        .stApp {
            background: linear-gradient(135deg, #05080d 0%, #07101a 45%, #02050a 100%);
            color: var(--eve-text);
        }

        .block-container {
            max-width: none;
            padding: 0.75rem 1.1rem 2rem 1.1rem;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #06101a 0%, #07131f 48%, #03070d 100%);
            border-right: 1px solid var(--eve-border);
        }

        [data-testid="stSidebar"] > div:first-child {
            padding-top: 0.9rem;
        }

        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label {
            color: var(--eve-text) !important;
        }

        [data-testid="stSidebar"] .stCaption,
        [data-testid="stSidebar"] p {
            color: var(--eve-muted);
        }

        h1, h2, h3 {
            letter-spacing: 0;
            color: var(--eve-text);
        }

        h2, h3 {
            font-size: 1rem;
            text-transform: uppercase;
        }

        .eve-sidebar-brand {
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            background: linear-gradient(135deg, rgba(18, 36, 52, 0.98), rgba(7, 15, 24, 0.95));
            padding: 0.9rem 0.95rem;
            margin-bottom: 0.85rem;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }

        .eve-sidebar-brand-title {
            color: #f8fafc;
            font-size: 0.95rem;
            font-weight: 800;
            letter-spacing: 0;
        }

        .eve-sidebar-brand-subtitle {
            color: var(--eve-muted);
            font-size: 0.76rem;
            margin-top: 0.2rem;
        }

        .eve-sidebar-section-title {
            color: #c8d5e3;
            font-size: 0.76rem;
            font-weight: 800;
            text-transform: uppercase;
            margin: 1rem 0 0.45rem 0;
        }

        .eve-sidebar-divider {
            height: 1px;
            background: var(--eve-border);
            margin: 0.9rem 0 0.8rem 0;
        }

        [data-testid="stSidebar"] .stRadio [role="radiogroup"] {
            gap: 0.25rem;
        }

        [data-testid="stSidebar"] .stRadio label {
            border: 1px solid transparent;
            border-radius: 8px;
            background: transparent;
            padding: 0.42rem 0.55rem;
            min-height: 2.25rem;
            transition: background 120ms ease, border-color 120ms ease;
        }

        [data-testid="stSidebar"] .stRadio label:hover {
            border-color: rgba(34, 211, 238, 0.2);
            background: rgba(14, 45, 63, 0.42);
        }

        [data-testid="stSidebar"] .stRadio label:has(input:checked) {
            border-color: rgba(34, 211, 238, 0.52);
            background: linear-gradient(90deg, rgba(34, 211, 238, 0.24), rgba(15, 23, 42, 0.18));
            box-shadow: inset 3px 0 0 var(--eve-cyan);
        }

        div[data-testid="stTabs"] button {
            color: #cbd5e1;
        }

        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: #f8fafc;
            border-bottom-color: var(--eve-cyan);
        }

        .eve-topbar {
            min-height: 3.4rem;
            margin: 0 0 0.85rem 0;
            padding: 0.65rem 0.85rem;
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(6, 15, 24, 0.98), rgba(5, 11, 18, 0.96));
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 12px 32px rgba(0, 0, 0, 0.2);
        }

        .eve-topbar-left,
        .eve-topbar-right {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            min-width: 0;
        }

        .eve-topbar-right {
            flex-wrap: wrap;
            justify-content: flex-end;
        }

        .eve-menu-mark {
            width: 2rem;
            height: 2rem;
            border-radius: 8px;
            border: 1px solid rgba(125, 211, 252, 0.2);
            color: var(--eve-cyan);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
        }

        .eve-app-title {
            color: #f8fafc;
            font-size: 1.18rem;
            font-weight: 850;
            line-height: 1.1;
        }

        .eve-app-subtitle {
            color: var(--eve-muted);
            font-size: 0.76rem;
            margin-top: 0.12rem;
        }

        .eve-top-pill {
            border: 1px solid rgba(125, 211, 252, 0.2);
            border-radius: 8px;
            background: rgba(13, 26, 38, 0.86);
            color: #cbd5e1;
            font-size: 0.78rem;
            padding: 0.32rem 0.5rem;
        }

        .eve-updated {
            color: var(--eve-muted);
            font-size: 0.78rem;
        }

        .eve-section-heading {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
            margin: 1rem 0 0.45rem 0;
        }

        .eve-section-title {
            color: #dce6f2;
            font-size: 0.84rem;
            font-weight: 850;
            text-transform: uppercase;
        }

        .eve-section-subtitle {
            color: var(--eve-muted);
            font-size: 0.78rem;
        }

        .eve-kpi {
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            padding: 0.95rem 1rem;
            background: linear-gradient(180deg, var(--eve-panel-2), rgba(4, 10, 17, 0.94));
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 12px 24px rgba(0,0,0,0.18);
            min-height: 6.4rem;
            display: flex;
            align-items: center;
            gap: 0.8rem;
        }

        .eve-kpi.success {
            border-color: rgba(53, 211, 95, 0.2);
        }

        .eve-kpi.danger {
            border-color: rgba(242, 95, 92, 0.26);
        }

        .eve-kpi.warning {
            border-color: rgba(229, 184, 75, 0.28);
        }

        .eve-kpi-icon {
            width: 2.7rem;
            height: 2.7rem;
            flex: 0 0 2.7rem;
            border-radius: 50%;
            border: 1px solid rgba(34, 211, 238, 0.22);
            background: rgba(34, 211, 238, 0.12);
            color: var(--eve-cyan);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 850;
            font-size: 0.8rem;
        }

        .eve-kpi-copy {
            min-width: 0;
        }

        .eve-kpi-label {
            color: var(--eve-muted);
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
        }

        .eve-kpi-value {
            color: #f8fafc;
            font-size: 1.45rem;
            font-weight: 800;
            margin-top: 0.3rem;
            line-height: 1.1;
        }

        .eve-kpi-delta {
            color: var(--eve-green);
            font-size: 0.86rem;
            margin-top: 0.25rem;
        }

        .eve-kpi.danger .eve-kpi-delta {
            color: var(--eve-red);
        }

        .eve-kpi.warning .eve-kpi-delta {
            color: var(--eve-amber);
        }

        .eve-badge {
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            padding: 0.18rem 0.45rem;
            background: rgba(15, 23, 42, 0.86);
            color: #cbd5e1;
            font-size: 0.74rem;
            font-weight: 800;
        }

        .eve-badge.success {
            border-color: rgba(53, 211, 95, 0.34);
            color: #7ee787;
            background: rgba(22, 101, 52, 0.22);
        }

        .eve-badge.danger {
            border-color: rgba(242, 95, 92, 0.34);
            color: #ff8b86;
            background: rgba(127, 29, 29, 0.24);
        }

        .eve-badge.warning {
            border-color: rgba(229, 184, 75, 0.36);
            color: #f6d365;
            background: rgba(120, 72, 18, 0.22);
        }

        .eve-list-panel {
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(9, 18, 29, 0.96), rgba(4, 10, 17, 0.9));
            padding: 0.55rem;
            display: grid;
            gap: 0.5rem;
            min-height: 8rem;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
        }

        .eve-alert-row,
        .eve-milestone-row {
            border: 1px solid rgba(125, 211, 252, 0.14);
            border-radius: 8px;
            background: rgba(8, 18, 29, 0.9);
            padding: 0.58rem 0.62rem;
        }

        .eve-alert-row.danger {
            border-color: rgba(242, 95, 92, 0.34);
            background: rgba(69, 18, 24, 0.28);
        }

        .eve-alert-row.warning {
            border-color: rgba(229, 184, 75, 0.34);
            background: rgba(74, 48, 16, 0.24);
        }

        .eve-alert-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.45rem;
            color: var(--eve-muted);
            font-size: 0.72rem;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }

        .eve-alert-title {
            color: #f8fafc;
            font-size: 0.88rem;
            font-weight: 850;
            line-height: 1.2;
        }

        .eve-alert-message {
            color: #cbd5e1;
            font-size: 0.78rem;
            line-height: 1.35;
            margin-top: 0.22rem;
        }

        .eve-alert-action {
            color: var(--eve-muted);
            font-size: 0.75rem;
            line-height: 1.35;
            margin-top: 0.28rem;
        }

        .eve-empty-state,
        .eve-list-more {
            color: var(--eve-muted);
            font-size: 0.82rem;
            padding: 0.7rem;
            text-align: center;
        }

        .eve-list-more {
            border-top: 1px solid rgba(125, 211, 252, 0.12);
            padding-top: 0.45rem;
        }

        .eve-detail-panel {
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(9, 18, 29, 0.96), rgba(4, 10, 17, 0.9));
            padding: 0.75rem;
            min-height: 100%;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
        }

        .eve-detail-heading {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.7rem;
            color: #f8fafc;
            font-size: 0.92rem;
            font-weight: 850;
            margin-bottom: 0.65rem;
        }

        .eve-detail-body {
            display: grid;
            gap: 0.45rem;
        }

        .eve-detail-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
            border-top: 1px solid rgba(125, 211, 252, 0.1);
            padding-top: 0.42rem;
        }

        .eve-detail-row span {
            color: var(--eve-muted);
            font-size: 0.78rem;
        }

        .eve-detail-row strong {
            color: #e5edf7;
            font-size: 0.82rem;
            text-align: right;
        }

        .eve-note {
            border: 1px solid rgba(34, 211, 238, 0.38);
            background: rgba(8, 47, 73, 0.42);
            border-radius: 8px;
            padding: 12px 14px;
            color: #dbeafe;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            overflow: hidden;
            background: rgba(7, 15, 24, 0.9);
        }

        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stBaseButton-secondary"],
        [data-testid="stBaseButton-primary"] {
            border-radius: 8px;
            border: 1px solid rgba(125, 211, 252, 0.22);
            background: rgba(13, 26, 38, 0.9);
            color: #e5edf7;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: var(--eve-border-strong);
            color: #f8fafc;
        }

        [data-testid="stMetric"] {
            border: 1px solid var(--eve-border);
            border-radius: 8px;
            padding: 0.7rem;
            background: rgba(7, 15, 24, 0.72);
        }

        .streamlit-expanderHeader {
            color: #dce6f2;
            font-weight: 750;
        }

        @media (max-width: 900px) {
            .eve-topbar {
                align-items: flex-start;
                flex-direction: column;
            }

            .eve-topbar-right {
                justify-content: flex-start;
            }

            .eve-kpi {
                min-height: 5.8rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
