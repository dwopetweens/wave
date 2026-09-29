#!/usr/bin/env python3
"""Generate the NDC Consulting Group pages as Elementor templates.

Run:  python3 tools/build_ndc_homepage.py
Out:  elementor/ndc-homepage.json and elementor/ndc-contact.json
      (import via Elementor > Templates > Import)

Only free Elementor widgets are used (container, heading, text-editor,
button, divider, icon, shortcode), so the pages stay fully editable in the
visual editor and need no custom CSS or Elementor Pro. The contact form
itself comes from the NDC Contact Form plugin in wordpress/.
"""

import itertools
import json
import pathlib

# --------------------------------------------------------------------------
# Design tokens (taken from the reference screenshots)
# --------------------------------------------------------------------------
INK = "#1A1A1A"          # dark sections + text on light sections
CREAM = "#F6F4E6"        # text on dark sections
SKY = "#6EC6EE"          # accent line + highlighted phrase
EYEBROW = "#2A87B4"      # small uppercase labels on light sections
MUTED = "#6B6B66"        # secondary copy on the services list
RULE_LIGHT = "#D9D6CC"   # hairlines on light sections
RULE_DARK = "#3A3A3A"    # hairlines on dark sections

BG_ABOUT = "#F4F3EF"
BG_SERVICES = "#F8F6EB"
BG_PROCESS = "#DFF0FA"

CONTACT_URL = "/contact/"

FONT_DISPLAY = "Inter Tight"
FONT_LEAD = "Manrope"
FONT_BODY = "DM Sans"

# Side gutters and vertical rhythm per breakpoint (desktop, tablet, mobile)
GUTTER = (36, 28, 20)
SECTION_Y = (140, 100, 72)

_ids = (f"{n:07x}" for n in itertools.count(0x1D0C001))


def uid():
    return next(_ids)


# --------------------------------------------------------------------------
# Small helpers for Elementor setting shapes
# --------------------------------------------------------------------------
def size(value, unit="px"):
    return {"unit": unit, "size": value, "sizes": []}


def custom(css):
    return {"unit": "custom", "size": css, "sizes": []}


def box(top=0, right=0, bottom=0, left=0, unit="px"):
    return {
        "unit": unit,
        "top": str(top),
        "right": str(right),
        "bottom": str(bottom),
        "left": str(left),
        "isLinked": False,
    }


def gap(row, column=None):
    column = row if column is None else column
    return {"unit": "px", "row": str(row), "column": str(column), "isLinked": row == column, "size": column}


def typo(family, px_or_css, weight="400", line_height=None, letter_spacing=None,
         transform=None, tablet=None, mobile=None):
    """Typography group. `px_or_css` may be an int (px) or a CSS string (clamp)."""
    s = {
        "typography_typography": "custom",
        "typography_font_family": family,
        "typography_font_weight": weight,
        "typography_font_size": size(px_or_css) if isinstance(px_or_css, (int, float)) else custom(px_or_css),
    }
    if tablet is not None:
        s["typography_font_size_tablet"] = size(tablet)
    if mobile is not None:
        s["typography_font_size_mobile"] = size(mobile)
    if line_height is not None:
        s["typography_line_height"] = size(line_height, "em")
    if letter_spacing is not None:
        s["typography_letter_spacing"] = size(letter_spacing, "em")
    if transform:
        s["typography_text_transform"] = transform
    return s


def section_padding(top=None, bottom=None):
    top = SECTION_Y if top is None else top
    bottom = SECTION_Y if bottom is None else bottom
    return {
        "padding": box(top[0], GUTTER[0], bottom[0], GUTTER[0]),
        "padding_tablet": box(top[1], GUTTER[1], bottom[1], GUTTER[1]),
        "padding_mobile": box(top[2], GUTTER[2], bottom[2], GUTTER[2]),
    }


# --------------------------------------------------------------------------
# Element builders
# --------------------------------------------------------------------------
def container(children, *, direction="column", justify=None, align=None, row_gap=0, col_gap=None,
              bg=None, width=None, width_tablet=None, width_mobile=None, padding=None,
              stack_on="mobile", wrap=False, html_tag=None, anchor=None, css_class=None,
              is_inner=True, extra=None):
    s = {
        "content_width": "full",
        "flex_direction": direction,
        "flex_gap": gap(row_gap, col_gap),
        "padding": box(),
    }
    if direction == "row" and stack_on:
        # Collapse rows into a single left-aligned column on smaller screens.
        for device in ("tablet", "mobile") if stack_on == "tablet" else ("mobile",):
            s[f"flex_direction_{device}"] = "column"
            s[f"flex_align_items_{device}"] = "flex-start"
    elif direction == "row":
        # Keep this row on one line at every size.
        s["flex_direction_tablet"] = s["flex_direction_mobile"] = "row"
        s["flex_wrap"] = "nowrap"
    if justify:
        s["flex_justify_content"] = justify
    if align:
        s["flex_align_items"] = align
    if wrap:
        s["flex_wrap"] = "wrap"
    if bg:
        s["background_background"] = "classic"
        s["background_color"] = bg
    if width is not None:
        s["width"] = size(width, "%")
    if width_tablet is not None:
        s["width_tablet"] = size(width_tablet, "%")
    if width_mobile is not None:
        s["width_mobile"] = size(width_mobile, "%")
    if padding:
        s.update(padding)
    if html_tag:
        s["html_tag"] = html_tag
    if anchor:
        s["_element_id"] = anchor
    if css_class:
        s["css_classes"] = css_class
    if extra:
        s.update(extra)
    return {"id": uid(), "elType": "container", "settings": s, "elements": children, "isInner": is_inner}


def widget(kind, settings):
    return {"id": uid(), "elType": "widget", "widgetType": kind, "settings": settings, "elements": []}


def heading(text, *, tag="h2", color=INK, typography, align=None, extra=None):
    s = {"title": text, "header_size": tag, "title_color": color, **typography}
    if align:
        s["align"] = align
    if extra:
        s.update(extra)
    return widget("heading", s)


def text(html, *, color=INK, typography, extra=None):
    s = {"editor": html, "text_color": color, **typography}
    if extra:
        s.update(extra)
    return widget("text-editor", s)


def eyebrow(label, color=EYEBROW, css=None):
    if css:
        t = typo(FONT_BODY, css, "700", 1.2, 0.2, "uppercase")
    else:
        t = typo(FONT_BODY, 17, "700", 1.2, 0.2, "uppercase", tablet=15, mobile=13)
    return heading(label, tag="p", color=color, typography=t)


def display(text_, color=INK, tag="h2", css="clamp(48px, 6.5vw, 136px)", tablet=None, mobile=None):
    return heading(text_, tag=tag, color=color,
                   typography=typo(FONT_DISPLAY, css, "600", 0.93, -0.045, tablet=tablet, mobile=mobile))


def body_copy(html, color=INK, css="clamp(17px, 1.2vw, 24px)", line_height=1.6):
    return text(html, color=color, typography=typo(FONT_BODY, css, "400", line_height))


def lead_copy(html, color=CREAM, css="clamp(22px, 2vw, 40px)"):
    return text(html, color=color, typography=typo(FONT_LEAD, css, "500", 1.35, -0.01))


def pill_button(label, url, *, on_dark=True, extra=None):
    fg, bg = (CREAM, INK) if on_dark else (INK, "transparent")
    s = {
        "text": label,
        "link": {"url": url, "is_external": "", "nofollow": "", "custom_attributes": ""},
        "button_text_color": fg,
        "background_background": "classic",
        "background_color": "rgba(0,0,0,0)",
        "hover_color": bg if on_dark else CREAM,
        "button_background_hover_background": "classic",
        "button_background_hover_color": fg,
        "button_hover_border_color": fg,
        "border_border": "solid",
        "border_width": box(2, 2, 2, 2),
        "border_color": fg,
        "border_radius": box(999, 999, 999, 999),
        "text_padding": box(26, 38, 26, 38),
        "text_padding_mobile": box(18, 28, 18, 28),
        "button_hover_transition_duration": size(0.25, "s"),
        **typo(FONT_BODY, 26, "700", 1, 0, tablet=21, mobile=18),
    }
    if extra:
        s.update(extra)
    return widget("button", s)


def arrow_link(label, url, css="clamp(18px, 1.35vw, 26px)", underline_gap=12):
    """Underlined text link with a trailing arrow, built from the button widget."""
    return widget("button", {
        "text": label,
        "link": {"url": url, "is_external": "", "nofollow": "", "custom_attributes": ""},
        "selected_icon": {"value": "fas fa-arrow-right", "library": "fa-solid"},
        "icon_align": "row-reverse",
        "icon_indent": size(14),
        "button_text_color": INK,
        "hover_color": EYEBROW,
        "button_hover_border_color": EYEBROW,
        "background_background": "classic",
        "background_color": "rgba(0,0,0,0)",
        "button_background_hover_background": "classic",
        "button_background_hover_color": "rgba(0,0,0,0)",
        "border_border": "solid",
        "border_width": box(0, 0, 2, 0),
        "border_color": INK,
        "border_radius": box(0, 0, 0, 0),
        "text_padding": box(0, 0, underline_gap, 0),
        **typo(FONT_BODY, css, "700", 1.2),
    })


def rule(color, weight=1, width_pct=100, width_px=None):
    s = {
        "style": "solid",
        "weight": size(weight),
        "color": color,
        "gap": size(0),
        "width": size(width_px) if width_px else size(width_pct, "%"),
    }
    if width_px:
        s["_element_width"] = "initial"
        s["_element_custom_width"] = size(width_px)
    return widget("divider", s)


def timeline_dot():
    """Filled circle that sits on the process timeline line."""
    return widget("icon", {
        "selected_icon": {"value": "fas fa-circle", "library": "fa-solid"},
        "primary_color": INK,
        "size": size(20),
        "align": "left",
        "_position": "absolute",
        "_offset_orientation_h": "start",
        "_offset_x": size(-1),
        "_offset_orientation_v": "start",
        "_offset_y": size(-11),
        "_z_index": 2,
    })


def sky(text_):
    return f'<span style="color:{SKY};">{text_}</span>'


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
def site_header(on_home=True):
    prefix = "" if on_home else "/"
    nav_link = lambda label, href: heading(  # noqa: E731
        f'<a href="{href}">{label}</a>', tag="p", color=CREAM,
        typography=typo(FONT_BODY, 17, "500", 1.2),
        extra={"hide_mobile": "hidden-mobile"},
    )
    return container(
        [
            heading('<a href="/">NDC Consulting Group</a>', tag="p", color=CREAM,
                    typography=typo(FONT_DISPLAY, 22, "600", 1, -0.02, mobile=18),
                    extra={"_flex_size": "grow"}),
            nav_link("About", f"{prefix}#about"),
            nav_link("Services", f"{prefix}#services"),
            nav_link("Process", f"{prefix}#process"),
            pill_button("Contact Us", CONTACT_URL,
                        extra={**typo(FONT_BODY, 16, "700", 1),
                               "text_padding": box(12, 24, 12, 24),
                               "text_padding_mobile": box(10, 18, 10, 18),
                               "border_width": box(1.5, 1.5, 1.5, 1.5)}),
        ],
        direction="row", align="center", bg=INK, stack_on=None, row_gap=36,
        padding=section_padding(top=(28, 24, 20), bottom=(28, 24, 20)),
        html_tag="header", is_inner=False,
    )


def hero():
    """Full-width photo hero. Set the photo in Elementor: select this container,
    then Style > Background > Image. The dark gradient keeps text legible."""
    return container(
        [
            container(
                [
                    eyebrow("Business operations consulting", color=CREAM),
                    display("Better systems make better work possible.", color=CREAM, tag="h1",
                            css="clamp(48px, 6.6vw, 136px)"),
                    lead_copy("For leaders ready to move from reactive problem-solving to intentional growth.",
                              css="clamp(19px, 1.6vw, 30px)"),
                    pill_button("Start the conversation", CONTACT_URL),
                ],
                width=62, width_tablet=90, width_mobile=100, row_gap=32, align="flex-start",
            ),
        ],
        justify="flex-end", bg=INK, anchor="top", html_tag="section", is_inner=False,
        padding=section_padding(top=(200, 160, 120), bottom=(120, 96, 72)),
        extra={
            "min_height": size(88, "vh"),
            "min_height_mobile": size(80, "vh"),
            "background_image": {"url": "", "id": "", "size": "", "alt": "", "source": "library"},
            "background_position": "center center",
            "background_repeat": "no-repeat",
            "background_size": "cover",
            "background_overlay_background": "gradient",
            "background_overlay_color": "rgba(26,26,26,0.88)",
            "background_overlay_color_stop": size(0, "%"),
            "background_overlay_color_b": "rgba(26,26,26,0.35)",
            "background_overlay_color_b_stop": size(100, "%"),
            "background_overlay_gradient_type": "linear",
            "background_overlay_gradient_angle": size(20, "deg"),
            "background_overlay_opacity": size(1, ""),
        },
    )


def why_ndc():
    return container(
        [
            container([display("Why<br>NDC?", color=CREAM, tag="h2", css="clamp(64px, 7.1vw, 148px)")],
                      width=45, width_tablet=100),
            container(
                [
                    lead_copy("As businesses grow, the systems that once worked often become "
                              "the very things holding them back."),
                    lead_copy("NDC Consulting Group identifies the gaps, inefficiencies, and operational "
                              "challenges affecting your company’s performance. We provide "
                              + sky("clear direction, practical solutions, and disciplined execution")
                              + " to help your business operate more effectively."),
                    lead_copy("Sustainable growth depends on more than ambition. It requires the right "
                              "systems, structure, and support to move your business forward."),
                ],
                width=50, width_tablet=100, row_gap=28,
            ),
        ],
        direction="row", justify="space-between", align="flex-start", bg=INK, stack_on="tablet",
        row_gap=48, padding=section_padding(), anchor="why", html_tag="section", is_inner=False,
    )


def about():
    return container(
        [
            container(
                [
                    eyebrow("About us", css="clamp(12px, 1.05vw, 17px)"),
                    heading("We make the business work better.", tag="h2", color=INK,
                            typography=typo(FONT_DISPLAY, "clamp(48px, 6.4vw, 132px)", "600", 0.92, -0.05)),
                ],
                width=38, width_tablet=100, row_gap=20,
            ),
            container(
                [
                    text("NDC Consulting Group is a business operations firm for leaders who are ready "
                         "to move from reactive problem-solving to intentional growth.",
                         color=INK, typography=typo(FONT_DISPLAY, "clamp(22px, 2.45vw, 48px)", "500", 1.27, -0.015)),
                    body_copy("We evaluate how work gets done, identify the gaps costing your company time "
                              "and trust, and build practical systems your team can actually use. Our work "
                              "connects strategy to execution across human resources, talent acquisition, "
                              "internal communications, customer retention, and marketing operations.",
                              css="clamp(16px, 1.45vw, 25px)", line_height=1.4),
                    arrow_link("Let’s talk about your business", CONTACT_URL,
                               css="clamp(16px, 1.5vw, 26px)", underline_gap=8),
                ],
                width=56, width_tablet=100, row_gap=30, align="flex-start",
            ),
        ],
        direction="row", justify="space-between", align="flex-start", bg=BG_ABOUT, stack_on="tablet",
        row_gap=48, padding=section_padding(top=(88, 80, 64), bottom=(104, 88, 72)),
        anchor="about", html_tag="section", is_inner=False,
    )


SERVICES = [
    ("01", "Human Resources",
     "Employee lifecycle systems, onboarding, policy development, compliance workflows, "
     "and performance processes designed for a growing team."),
    ("02", "Internal Communications",
     "Communication structures, leadership messaging, and change communications "
     "that keep teams informed and aligned."),
    ("03", "Customer Retention & Recovery",
     "Escalation protocols, service recovery systems, and response standards "
     "that help resolve issues and rebuild trust."),
    ("04", "Marketing Operations",
     "Campaign workflows, content processes, and clear team responsibilities "
     "that help turn plans into consistent execution."),
]


def service_row(num, title, desc, last=False):
    border = box(1, 0, 1 if last else 0, 0)
    return container(
        [
            container([heading(num, tag="p", color=EYEBROW, typography=typo(FONT_BODY, 20, "700", 1.2, mobile=16))],
                      width=9, width_tablet=10, width_mobile=100),
            container([heading(title, tag="h3", color=INK,
                               typography=typo(FONT_DISPLAY, "clamp(30px, 2.7vw, 54px)", "600", 1.05, -0.04))],
                      width=44, width_tablet=38, width_mobile=100, extra={"padding": box(18, 0, 0, 0),
                                                                         "padding_mobile": box(0, 0, 0, 0)}),
            container([body_copy(desc, color=MUTED, css="clamp(17px, 1.2vw, 24px)")],
                      width=43, width_tablet=48, width_mobile=100),
        ],
        direction="row", justify="space-between", align="flex-start", row_gap=16,
        extra={
            "border_border": "solid",
            "border_width": border,
            "border_color": RULE_LIGHT,
            "padding": box(56, 0, 56, 0),
            "padding_mobile": box(36, 0, 36, 0),
        },
    )


def services():
    return container(
        [
            container(
                [
                    container([eyebrow("What we do"), display("Operational clarity, where it counts.")],
                              width=55, width_tablet=100, row_gap=28),
                    container([body_copy("Focused consulting support for the parts of your business that "
                                         "shape performance, culture, and customer trust.")],
                              width=36, width_tablet=80, width_mobile=100),
                ],
                direction="row", justify="space-between", align="flex-end", stack_on="tablet", row_gap=32,
            ),
            container([service_row(*s, last=i == len(SERVICES) - 1) for i, s in enumerate(SERVICES)]),
        ],
        bg=BG_SERVICES, row_gap=88, padding=section_padding(), anchor="services", html_tag="section",
        is_inner=False,
    )


STEPS = [
    ("01 / Discover", "Understand the reality",
     "We listen to leadership, review current workflows, and uncover the issues beneath the symptoms."),
    ("02 / Design", "Build the right system",
     "We create a focused solution around your goals, team capacity, and stage of growth."),
    ("03 / Implement", "Make it operational",
     "We support execution, clarify ownership, and help your team put the new process to work."),
]


def process_step(label, title, desc):
    return container(
        [
            timeline_dot(),
            heading(label, tag="p", color=INK, typography=typo(FONT_BODY, 20, "700", 1.2, 0, "uppercase", mobile=16)),
            heading(title, tag="h3", color=INK,
                    typography=typo(FONT_DISPLAY, "clamp(26px, 1.9vw, 38px)", "600", 1.1, -0.04)),
            body_copy(desc),
        ],
        width=33.333, width_tablet=33.333, width_mobile=100, row_gap=24,
        extra={
            "border_border": "solid",
            "border_width": box(2, 0, 0, 0),
            "border_color": INK,
            "padding": box(72, 96, 0, 0),
            "padding_tablet": box(56, 32, 0, 0),
            "padding_mobile": box(48, 0, 16, 0),
        },
    )


def process():
    return container(
        [
            container(
                [
                    container([eyebrow("Our process"), display("Listen.<br>Diagnose. Build.")],
                              width=52, width_tablet=100, row_gap=28),
                    container([body_copy("We do not hand you a glossy strategy that collects dust. We learn "
                                         "the business, find what is getting in the way, and build a clear "
                                         "path forward.")],
                              width=43, width_tablet=80, width_mobile=100),
                ],
                direction="row", justify="space-between", align="center", stack_on="tablet", row_gap=32,
            ),
            container([process_step(*s) for s in STEPS], direction="row", row_gap=0, col_gap=0,
                      extra={"flex_gap_mobile": gap(24, 0)}),
        ],
        bg=BG_PROCESS, row_gap=96, padding=section_padding(), anchor="process", html_tag="section",
        is_inner=False,
    )


def site_footer():
    small = typo(FONT_BODY, 18, "400", 1.4, tablet=16, mobile=14)
    return container(
        [
            heading("© 2026 NDC Consulting Group. All rights reserved.", tag="p", color="#BDBBAF", typography=small),
            heading("Built for better business.", tag="p", color="#BDBBAF", typography=small),
        ],
        direction="row", justify="space-between", align="center", row_gap=8,
        padding=section_padding(top=(28, 24, 24), bottom=(28, 24, 24)),
        html_tag="footer",
        extra={"border_border": "solid", "border_width": box(1, 0, 0, 0), "border_color": RULE_DARK},
    )


def contact_and_footer():
    cta = container(
        [
            container(
                [
                    container([rule(SKY, weight=3, width_px=60), eyebrow("Start the conversation", color=CREAM)],
                              direction="row", align="center", row_gap=18, stack_on=None),
                    display("Your business can run better.", color=CREAM, tag="h2", css="clamp(48px, 7.4vw, 152px)"),
                ],
                row_gap=24, width=62, width_tablet=100,
            ),
            pill_button("Contact Us", CONTACT_URL),
        ],
        direction="row", justify="space-between", align="center", stack_on="tablet", row_gap=40,
        padding=section_padding(top=(140, 100, 72), bottom=(140, 100, 72)),
        anchor="contact",
    )
    return container([cta, site_footer()], bg=INK, is_inner=False)


def contact_form_section():
    return container(
        [
            container(
                [
                    eyebrow("Contact", css="clamp(12px, 1.05vw, 17px)"),
                    display("Let’s talk about your business.", css="clamp(44px, 5vw, 104px)"),
                    body_copy("Tell us about your company and what you are looking for. "
                              "All fields are required, and we will be in touch soon.",
                              css="clamp(16px, 1.3vw, 22px)"),
                ],
                width=36, width_tablet=100, row_gap=24,
            ),
            container(
                [widget("shortcode", {"shortcode": "[ndc_contact_form]"})],
                width=58, width_tablet=100,
            ),
        ],
        direction="row", justify="space-between", align="flex-start", bg=BG_ABOUT, stack_on="tablet",
        row_gap=56, padding=section_padding(top=(120, 96, 64), bottom=(140, 104, 80)),
        anchor="contact-form", html_tag="section", is_inner=False,
        extra={"min_height": custom("calc(100vh - 180px)")},
    )


# --------------------------------------------------------------------------
def page(title, content):
    return {
        "content": content,
        "page_settings": {
            "template": "elementor_canvas",
            "hide_title": "yes",
            "background_background": "classic",
            "background_color": INK,
        },
        "version": "0.4",
        "title": title,
        "type": "page",
    }


def build():
    return page("NDC Consulting Group – Homepage",
                [site_header(), hero(), why_ndc(), about(), services(), process(), contact_and_footer()])


def build_contact():
    return page("NDC Consulting Group – Contact",
                [site_header(on_home=False), contact_form_section(),
                 container([site_footer()], bg=INK, is_inner=False)])


if __name__ == "__main__":
    out_dir = pathlib.Path(__file__).resolve().parent.parent / "elementor"
    out_dir.mkdir(exist_ok=True)
    for name, builder in (("ndc-homepage.json", build), ("ndc-contact.json", build_contact)):
        out = out_dir / name
        out.write_text(json.dumps(builder(), indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {out}")
