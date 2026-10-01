#!/usr/bin/env python3
"""Generate the NDC Consulting Group pages as Elementor templates.

Run:  python3 tools/build_ndc_homepage.py
Out:  elementor/ndc-homepage.json, ndc-contact.json  (pages)
      elementor/ndc-header.json, ndc-footer.json     (site header/footer)
      (import via Elementor > Templates > Import)

Only free Elementor widgets are used (container, heading, text-editor,
button, divider, icon, shortcode), so the pages stay fully editable in the
visual editor and need no custom CSS or Elementor Pro. The contact form
itself comes from the NDC Contact Form plugin in wordpress/.
"""

import base64
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

BG_ABOUT = "#F4F3EF"

CONTACT_URL = "/contact/"

BLACK = "#000000"
WHITE = "#FFFFFF"

# Footer contact details: placeholders until the client confirms them.
FOOTER_PHONE = "(000) 000-0000"
FOOTER_PHONE_LINK = "tel:+10000000000"
FOOTER_EMAIL = "nadiaworsley@gmail.com"

# Hero photo: left empty so the template imports quickly. The NDC Hello Child
# theme's "Add homepage photo" button (Appearance > NDC Site Status)
# downloads the Higgsfield team photo and sets it here.
HERO_IMAGE = {"url": "", "id": "", "size": "", "alt": "", "source": "library"}

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


def timeline_dot(color=INK):
    """Filled circle that sits on the process timeline line."""
    return widget("icon", {
        "selected_icon": {"value": "fas fa-circle", "library": "fa-solid"},
        "primary_color": color,
        "size": size(20),
        "align": "left",
        "_position": "absolute",
        "_offset_orientation_h": "start",
        "_offset_x": size(-1),
        "_offset_orientation_v": "start",
        "_offset_y": size(-11),
        "_z_index": 2,
    })


def nav_link(label, href, size_px=17, hide_mobile=True):
    return heading(
        f'<a href="{href}">{label}</a>', tag="p", color=CREAM,
        typography=typo(FONT_BODY, size_px, "500", 1.2),
        extra={"hide_mobile": "hidden-mobile"} if hide_mobile else None,
    )


LOGO_FILE = pathlib.Path(__file__).resolve().parent.parent / "wordpress/ndc-hello-child/assets/img/ndc-logo-light-200.png"
LOGO_RATIO = 894 / 371


def logo(height=64, height_mobile=46):
    """Cream NDC logo embedded in an HTML widget, so it shows up with or
    without the child theme and needs no media upload on import."""
    data = base64.b64encode(LOGO_FILE.read_bytes()).decode()
    cls = f"ndc-logo--{height}"
    html = (
        f'<a class="ndc-logo-link" href="/" rel="home" aria-label="NDC Consulting Group home">'
        f'<img class="ndc-logo {cls}" src="data:image/png;base64,{data}" '
        f'width="{round(height * LOGO_RATIO)}" height="{height}" alt="NDC Consulting Group" '
        f'style="display:block;height:{height}px;width:auto;max-width:100%"></a>'
        f'<style>@media (max-width:767px){{img.ndc-logo.{cls}{{height:{height_mobile}px!important}}}}</style>'
    )
    return widget("html", {"html": html, "_flex_size": "grow"})


NAV = [("About", "/#about"), ("Services", "/#services"), ("Process", "/#process")]


def site_header():
    return container(
        [
            logo(),
            *[nav_link(label, href) for label, href in NAV],
            nav_link("Contact Us", CONTACT_URL, hide_mobile=False),
        ],
        direction="row", align="center", bg=BLACK, stack_on=None, row_gap=36,
        padding=section_padding(top=(18, 16, 14), bottom=(18, 16, 14)),
        is_inner=False,
    )


def hero():
    """Full-width photo hero. The photo is the container's background image
    (Style > Background > Image in Elementor); the dark gradient keeps the
    headline legible."""
    return container(
        [
            container(
                [
                    display("Your business can’t grow on broken systems.", color=WHITE, tag="h1",
                            css="clamp(44px, 5.6vw, 116px)"),
                    lead_copy("NDC Consulting Group strengthens the systems, processes, and teams your "
                              "business depends on to operate efficiently and deliver a better customer "
                              "experience.", color=WHITE, css="clamp(18px, 1.5vw, 28px)"),
                    pill_button("Contact Us", CONTACT_URL, on_dark=True,
                                extra={**typo(FONT_BODY, 17, "700", 1, 0, mobile=16),
                                       "text_padding": box(14, 28, 14, 28),
                                       "text_padding_mobile": box(12, 24, 12, 24),
                                       "border_width": box(1.5, 1.5, 1.5, 1.5),
                                       "button_text_color": WHITE, "border_color": WHITE,
                                       "button_background_hover_color": WHITE,
                                       "button_hover_border_color": WHITE, "hover_color": BLACK}),
                ],
                width=60, width_tablet=90, width_mobile=100, row_gap=28, align="flex-start",
            ),
        ],
        justify="flex-end", bg=BLACK, anchor="top", html_tag="section", is_inner=False,
        padding=section_padding(top=(200, 160, 120), bottom=(120, 96, 72)),
        extra={
            "min_height": size(88, "vh"),
            "min_height_mobile": size(80, "vh"),
            "background_image": HERO_IMAGE,
            "background_position": "center center",
            "background_position_mobile": "center right",
            "background_repeat": "no-repeat",
            "background_size": "cover",
            "background_overlay_background": "gradient",
            "background_overlay_color": "rgba(0,0,0,0.86)",
            "background_overlay_color_stop": size(0, "%"),
            "background_overlay_color_b": "rgba(0,0,0,0.15)",
            "background_overlay_color_b_stop": size(100, "%"),
            "background_overlay_gradient_type": "linear",
            "background_overlay_gradient_angle": size(70, "deg"),
            "background_overlay_opacity": size(1, ""),
        },
    )


def why_ndc():
    return container(
        [
            container([display("Why<br>NDC?", color=WHITE, tag="h2", css="clamp(64px, 7.1vw, 148px)")],
                      width=45, width_tablet=100),
            container(
                [
                    lead_copy("As businesses grow, the systems that once worked often become "
                              "the very things holding them back.", color=WHITE),
                    lead_copy("NDC Consulting Group identifies the gaps, inefficiencies, and operational "
                              "challenges affecting your company’s performance. We provide clear direction, "
                              "practical solutions, and disciplined execution to help your business operate "
                              "more effectively.", color=WHITE),
                    lead_copy("Sustainable growth depends on more than ambition. It requires the right "
                              "systems, structure, and support to move your business forward.", color=WHITE),
                ],
                width=50, width_tablet=100, row_gap=28,
            ),
        ],
        direction="row", justify="space-between", align="flex-start", bg=BLACK, stack_on="tablet",
        row_gap=48, padding=section_padding(), anchor="why", html_tag="section", is_inner=False,
    )


def about():
    return container(
        [
            container(
                [
                    eyebrow("About us", color=BLACK, css="clamp(12px, 1.05vw, 17px)"),
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
                              "connects strategy to execution across human resources, internal communications, "
                              "customer retention, and marketing operations.",
                              css="clamp(16px, 1.45vw, 25px)", line_height=1.4),
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


def service_row(num, title, desc):
    return container(
        [
            container([heading(num, tag="p", color=BLACK, typography=typo(FONT_BODY, 20, "700", 1.2, mobile=16))],
                      width=9, width_tablet=10, width_mobile=100),
            container([heading(title, tag="h3", color=BLACK,
                               typography=typo(FONT_DISPLAY, "clamp(30px, 2.7vw, 54px)", "600", 1.05, -0.04))],
                      width=44, width_tablet=38, width_mobile=100, extra={"padding": box(18, 0, 0, 0),
                                                                         "padding_mobile": box(0, 0, 0, 0)}),
            container([body_copy(desc, color=BLACK, css="clamp(17px, 1.2vw, 24px)")],
                      width=43, width_tablet=48, width_mobile=100),
        ],
        direction="row", justify="space-between", align="flex-start", row_gap=16,
        extra={
            "padding": box(44, 0, 44, 0),
            "padding_mobile": box(28, 0, 28, 0),
        },
    )


def services():
    return container(
        [
            container(
                [
                    container([eyebrow("What we do", color=BLACK),
                               display("Operational clarity, where it counts.", color=BLACK)],
                              width=55, width_tablet=100, row_gap=28),
                    container([body_copy("Focused consulting support for the parts of your business that "
                                         "shape performance, culture, and customer trust.", color=BLACK)],
                              width=36, width_tablet=80, width_mobile=100),
                ],
                direction="row", justify="space-between", align="flex-end", stack_on="tablet", row_gap=32,
            ),
            container([service_row(*s) for s in SERVICES]),
        ],
        bg=WHITE, row_gap=56, padding=section_padding(), anchor="services", html_tag="section",
        is_inner=False,
    )


STEPS = [
    ("01 / Discover", "Understand Your Business",
     "We review how work gets done, listen to your team, and identify the gaps affecting efficiency, "
     "performance, and customer experience."),
    ("02 / Design", "Develop the Right Solution",
     "We create practical processes, clarify responsibilities, and build an action plan around your "
     "business goals and team’s needs."),
    ("03 / Implement", "Make It Work Every Day",
     "We help your team put the plan into action with clear guidance, defined ownership, and support "
     "to keep improvements on track."),
]


def process_step(label, title, desc):
    return container(
        [
            timeline_dot(WHITE),
            heading(label, tag="p", color=WHITE, typography=typo(FONT_BODY, 20, "700", 1.2, 0, "uppercase", mobile=16)),
            heading(title, tag="h3", color=WHITE,
                    typography=typo(FONT_DISPLAY, "clamp(26px, 1.9vw, 38px)", "600", 1.1, -0.04)),
            body_copy(desc, color=WHITE),
        ],
        width=33.333, width_tablet=33.333, width_mobile=100, row_gap=24,
        extra={
            "border_border": "solid",
            "border_width": box(2, 0, 0, 0),
            "border_color": WHITE,
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
                    container([eyebrow("Our process", color=WHITE),
                               display("Listen.<br>Diagnose. Build.", color=WHITE)],
                              width=52, width_tablet=100, row_gap=28),
                    container([body_copy("We assess how your business runs, pinpoint what needs to improve, and "
                                         "put practical solutions in place to help it run more effectively.",
                                         color=WHITE)],
                              width=43, width_tablet=80, width_mobile=100),
                ],
                direction="row", justify="space-between", align="center", stack_on="tablet", row_gap=32,
            ),
            container([process_step(*s) for s in STEPS], direction="row", row_gap=0, col_gap=0,
                      extra={"flex_gap_mobile": gap(24, 0)}),
        ],
        bg=BLACK, row_gap=96, padding=section_padding(), anchor="process", html_tag="section",
        is_inner=False,
    )


def site_footer():
    """One black bar: phone and email on the left, copyright on the right."""
    small = typo(FONT_BODY, 15, "400", 1.5, mobile=13)
    contact = widget("icon-list", {
        "view": "inline",
        "icon_list": [
            {"_id": uid(), "text": FOOTER_PHONE,
             "selected_icon": {"value": "fas fa-phone", "library": "fa-solid"},
             "link": {"url": FOOTER_PHONE_LINK, "is_external": "", "nofollow": "", "custom_attributes": ""}},
            {"_id": uid(), "text": FOOTER_EMAIL,
             "selected_icon": {"value": "far fa-envelope-open", "library": "fa-regular"},
             "link": {"url": f"mailto:{FOOTER_EMAIL}", "is_external": "", "nofollow": "", "custom_attributes": ""}},
        ],
        "space_between": size(36),
        "icon_color": WHITE,
        "icon_size": size(18),
        "text_indent": size(10),
        "text_color": WHITE,
        "text_color_hover": SKY,
        **{k.replace("typography_", "icon_typography_", 1): v
           for k, v in typo(FONT_BODY, 19, "400", 1.3, mobile=16).items()},
    })
    legal = container(
        [
            heading("Copyright 2026 © NDC Consulting Group", tag="p", color=WHITE, typography=small,
                    align="right", extra={"align_mobile": "left"}),
        ],
        row_gap=4, align="flex-end",
        extra={"_flex_size": "none", "width": size(40, "%"), "width_mobile": size(100, "%"),
               "flex_align_items_mobile": "flex-start"},
    )
    return container(
        [container([contact], extra={"_flex_size": "none", "width": size(58, "%"), "width_mobile": size(100, "%")}),
         legal],
        direction="row", justify="space-between", align="center", row_gap=20, bg=BLACK, is_inner=False,
        padding=section_padding(top=(28, 24, 24), bottom=(28, 24, 28)),
    )


def contact_cta():
    return container(
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
        anchor="contact", bg=BLACK, is_inner=False,
    )


def contact_form_section():
    return container(
        [
            container(
                [
                    eyebrow("Contact", color=BLACK, css="clamp(12px, 1.05vw, 17px)"),
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
    )


# --------------------------------------------------------------------------
def page(title, content):
    # "Elementor Full Width" keeps the theme header/footer (the NDC Site
    # Header/Footer templates, via the NDC Hello Child theme).
    return {
        "content": content,
        "page_settings": {"template": "elementor_header_footer", "hide_title": "yes"},
        "version": "0.4",
        "title": title,
        "type": "page",
    }


def part(title, content):
    return {"content": content, "page_settings": [], "version": "0.4", "title": title, "type": "section"}


def build():
    return page("NDC Consulting Group – Homepage",
                [hero(), why_ndc(), about(), services(), process(), contact_cta()])


def build_contact():
    return page("NDC Consulting Group – Contact", [contact_form_section()])


def build_header():
    return part("NDC Site Header", [site_header()])


def build_footer():
    return part("NDC Site Footer", [site_footer()])


if __name__ == "__main__":
    out_dir = pathlib.Path(__file__).resolve().parent.parent / "elementor"
    out_dir.mkdir(exist_ok=True)
    for name, builder in (("ndc-homepage.json", build), ("ndc-contact.json", build_contact),
                          ("ndc-header.json", build_header), ("ndc-footer.json", build_footer)):
        out = out_dir / name
        out.write_text(json.dumps(builder(), indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {out}")
    # The child theme bundles the header/footer and imports them if missing.
    theme_tpl = out_dir.parent / "wordpress" / "ndc-hello-child" / "templates"
    theme_tpl.mkdir(exist_ok=True)
    for name in ("ndc-header.json", "ndc-footer.json"):
        (theme_tpl / name).write_text((out_dir / name).read_text())
        print(f"wrote {theme_tpl / name}")
