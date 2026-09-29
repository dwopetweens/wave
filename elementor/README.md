# NDC Consulting Group: website (Elementor + Hello)

This folder has two Elementor page templates and the contact-form plugin they rely on.

| File | What it is |
| --- | --- |
| `ndc-homepage.json` | The homepage template. |
| `ndc-contact.json` | The contact page template. |
| `../wordpress/ndc-contact-form.zip` | The contact form plugin, with spam protection. It emails each enquiry to **nadiaworsley@gmail.com**. |

**Homepage sections:**
1. **Header**: NDC wordmark, About / Services / Process links, and a Contact Us button.
2. **Hero**: a full-width photo with the headline "Better systems make better work possible." and a "Start the conversation" button. *You add the photo; see below.*
3. **Why NDC?**: the copy from *Why NDC Consulting Group – Homepage.docx*.
4. **About us**.
5. **What we do**: Human Resources, Internal Communications, Customer Retention & Recovery, Marketing Operations.
6. **Our process**: Discover → Design → Implement.
7. **Start the conversation**: a call to action, plus the footer.

**Contact page:** the same header and footer, with a form for Full Name (first and last), Company / Organization, Email and Message. Every field is required.

**Links:** every Contact button on the site goes to `/contact/`. Your email address never appears on the site itself, so spam bots can't harvest it.

The pages use only **free Elementor** widgets, and the form comes from the included plugin, so you don't need Elementor Pro. Everything was tested on WordPress 6.9.4, Hello Elementor 3.4.7 and Elementor 4.0.0.

![Desktop preview](preview/homepage-desktop.png)

## Install

1. **Theme:** activate **Hello Elementor** (*Appearance → Themes*).
2. **Elementor:** install and activate **Elementor**.
   On Elementor 3.x, check that *Elementor → Settings → Features → Flexbox Container* is **Active**.
3. **Contact form plugin:** *Plugins → Add New → Upload Plugin* → choose `wordpress/ndc-contact-form.zip` → **Install Now** → **Activate**.
4. **Import both templates:** *Templates → Saved Templates → Import Templates*. Import `ndc-homepage.json`, then `ndc-contact.json`.
5. **Create the pages:**
   - **Home:** *Pages → Add New* → title **Home** → **Edit with Elementor**. Click the folder icon → **My Templates** → **Insert** next to *NDC Consulting Group – Homepage*.
   - **Contact:** *Pages → Add New* → title **Contact**. The web address must be `/contact/`, which WordPress sets automatically from that title. → **Edit with Elementor** → insert *NDC Consulting Group – Contact*.
   - **For both pages:** open the page settings (gear icon) → **Page Layout → Elementor Canvas** → **Publish**.
6. **Set the homepage:** *Settings → Reading → A static page → Homepage: Home*.

## Adding the hero photo

The hero has a photo slot with a dark gradient over it, so the white text stays readable.

**To set the photo:**
1. Edit **Home** with Elementor.
2. Click the hero section (the one with "Better systems make better work possible.") to select it.
3. Go to **Style → Background → Image** → choose your photo → **Update**.

**What to look for in the photo:**
- A **landscape** photo, at least **2400 px wide**.
- The people are best placed **centre-right**. The headline sits on the left, so faces there would be covered.
- A real working moment (people around a table, a whiteboard, a laptop) reads better than a posed line-up.

**Free sources with strong, genuinely diverse business photos** (all free for commercial use):
- **nappy.co**: photos centred on Black and Brown people. Search "meeting" or "office".
- **Pexels**: search "diverse team meeting" or "black woman business meeting". The *#WOCinTech Chat* photos by Christina Morillo are a good fit.
- **Unsplash**: search "diverse team collaboration".

Before you publish, check the photo's licence page. Unsplash, Pexels and nappy.co photos need no attribution.

## Spam protection

The form stops bots without a CAPTCHA puzzle for real visitors. Each submission has to pass all of these checks:

| Check | What it catches |
| --- | --- |
| **Hidden trap field** | People never see it; bots fill it in. |
| **Signed form token** | Rejects forms posted directly to the site without loading the page. |
| **Human-interaction proof** | JavaScript only marks the form valid after a real key press or tap. Most bots never trigger that. |
| **Time trap** | Rejects submissions made less than 4 seconds after the page loaded. |
| **Rate limit** | At most 5 messages per visitor per hour. |
| **Content rules** | Blocks links in names, `[url]`/HTML link spam, and messages with more than 2 links. It also honours *Settings → Discussion → Disallowed Comment Keys*. |

**Bots are shown a fake "sent" message**, so they get no signal to adapt to. Nothing reaches your inbox.

**Optional extra layer: Cloudflare Turnstile.** It's free and usually invisible to visitors. If spam still gets through, create a Turnstile widget at dash.cloudflare.com and paste its **Site key** and **Secret key** into *Settings → NDC Contact Form*.

## Where enquiries go

- **Email:** every enquiry is emailed to **nadiaworsley@gmail.com**. Hitting **Reply** answers the person who wrote in. To change the address or add another, go to *Settings → NDC Contact Form*.
- **Saved copy:** each enquiry is also saved in WordPress under **Enquiries** in the admin menu, so nothing is lost if an email goes astray.

**Email delivery:** many hosts send WordPress email in a way Gmail treats as spam. After launching, send yourself a test enquiry. If it doesn't arrive, or lands in Spam, install the free **WP Mail SMTP** plugin and connect it to your email provider.

## Things to review

| Where | What |
| --- | --- |
| Hero | The eyebrow, headline and subline are placeholder copy drawn from your existing wording. Edit them in Elementor if you want different text. |
| Footer | The copyright year is plain text (`© 2026`). |

## Design tokens

| Token | Value | Used for |
| --- | --- | --- |
| Ink | `#1A1A1A` | Dark sections, text on light sections |
| Cream | `#F6F4E6` | Text on dark sections |
| Sky | `#6EC6EE` | Accent line, highlighted phrase |
| Eyebrow blue | `#2A87B4` | Small uppercase labels |
| About / Contact background | `#F4F3EF` | |
| Services background | `#F8F6EB` | |
| Process background | `#DFF0FA` | |

**Fonts (loaded automatically from Google Fonts by Elementor):**
- **Inter Tight** for headlines.
- **Manrope** for the large "Why NDC?" paragraphs.
- **DM Sans** for body text, labels, buttons and the form.

## Regenerating the templates

Both templates are generated by `tools/build_ndc_homepage.py`. To regenerate them after editing it:

```bash
python3 tools/build_ndc_homepage.py
```

Once the templates are imported, you can edit the pages directly in Elementor. The script is only for bulk changes.
