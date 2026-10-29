"""Fonction Vercel : reçoit une proposition d'événement et l'envoie par e-mail.

Variables d'environnement (Vercel > Settings > Environment Variables) :
  SMTP_USER      adresse Gmail qui envoie (ex. tphilipponneau@gmail.com)
  SMTP_PASSWORD  mot de passe d'application Gmail (16 caractères, pas le mot de passe du compte)
  MAIL_TO        destinataire (défaut : tphilipponneau@gmail.com)
  SMTP_HOST      défaut smtp.gmail.com
  SMTP_PORT      défaut 465 (SSL)
"""

import html
import json
import os
import re
import smtplib
import unicodedata
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler

MAX_BODY = 200_000

REQUIRED = {
    "title": "Titre",
    "period": "Période",
    "dates_text": "Dates et horaires",
    "audience": "Type de public",
    "description": "Texte de présentation",
    "visuals_url": "Lien des visuels",
}

EVENT_TYPES = {"391": "Atelier", "419": "Manifestations nationales", "282": "Conférences",
               "346": "Evénement", "80": "Exposition", "353": "Projection", "283": "Visites"}
PLACES = {"78": "Musée national de Préhistoire", "354": "Abri Pataud",
          "434": "Musée national de Préhistoire & Abri Pataud", "437": "Hors les murs"}

MAX_TICKETS = 5
ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "s", "h2", "h3", "ul", "ol", "li", "a"}
VOID_TAGS = {"br"}


class Sanitizer(HTMLParser):
    """Ne garde que les balises de mise en forme simples produites par l'éditeur."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.text = [], []
        self.skip = 0  # contenu de <script>/<style> ignoré

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
            return
        if tag not in ALLOWED_TAGS:
            return
        if tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            if not href.lower().startswith(("http://", "https://", "mailto:")):
                self.out.append("<a>")
                return
            self.out.append(f'<a href="{html.escape(href, quote=True)}">')
        else:
            self.out.append(f"<{tag}>")
        if tag in ("br", "p", "li", "h2", "h3"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(html.escape(data, quote=False))
        self.text.append(data)


def sanitize_html(value, limit=60000):
    if not isinstance(value, str):
        return "", ""
    parser = Sanitizer()
    parser.feed(value[:limit])
    parser.close()
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.text)).strip()
    return ("".join(parser.out) if text else ""), text


def clean(value, limit=8000):
    """Texte simple, sans caractères de contrôle (hors retours à la ligne), tronqué."""
    if not isinstance(value, str):
        return ""
    value = "".join(c for c in value if c in "\n\t" or unicodedata.category(c)[0] != "C")
    return value.strip()[:limit]


def one_line(value, limit=255):
    return " ".join(clean(value, limit).split())


def normalize(raw):
    """Reconstruit une fiche propre à partir du JSON reçu (on ne fait confiance à rien)."""
    et = str((raw.get("event_type") or {}).get("id", ""))
    pl = str((raw.get("place") or {}).get("id", ""))
    infos = []
    for item in (raw.get("useful_information") or [])[:10]:
        if isinstance(item, dict):
            t, x = one_line(item.get("title")), clean(item.get("text"), 2000)
            if t or x:
                infos.append({"title": t, "text": x})
    tickets = []
    for item in (raw.get("ticket_office") or [])[:MAX_TICKETS]:
        if isinstance(item, dict) and one_line(item.get("url"), 2048):
            tickets.append({"url": one_line(item.get("url"), 2048), "title": one_line(item.get("title"))})
    desc_html, desc_text = sanitize_html(raw.get("description"))
    assoc = [one_line(a) for a in (raw.get("associated_content") or [])[:3] if one_line(a)]
    return {
        "title": one_line(raw.get("title")),
        "subtitle": one_line(raw.get("subtitle"), 250),
        "event_type": {"id": et if et in EVENT_TYPES else "", "label": EVENT_TYPES.get(et, "")},
        "presenter_name": one_line(raw.get("presenter_name"), 150),
        "period": one_line(raw.get("period"), 250),
        "dates_text": clean(raw.get("dates_text"), 2000),
        "duration": one_line(raw.get("duration"), 55),
        "place": {"id": pl if pl in PLACES else "", "label": PLACES.get(pl, "")},
        "audience": one_line(raw.get("audience"), 200),
        "age_group": one_line(raw.get("age_group"), 55),
        "description": desc_html,
        "description_text": desc_text[:8000],
        "useful_information": infos,
        "ticket_office": tickets,
        "visuals_url": one_line(raw.get("visuals_url"), 2048),
        "copyright": one_line(raw.get("copyright")),
        "linked_event": one_line(raw.get("linked_event")),
        "associated_content": assoc,
        "message": clean(raw.get("message"), 2000),
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def validate(d):
    missing = [label for key, label in REQUIRED.items() if not d[key]]
    if not d["event_type"]["id"]:
        missing.append("Type d'événement")
    if not d["place"]["id"]:
        missing.append("Lieu")
    if d["visuals_url"] and not d["visuals_url"].startswith(("http://", "https://")):
        missing.append("Lien des visuels (doit commencer par https://)")
    return missing


def as_text(d):
    lines = []

    def add(k, v):
        if v:
            lines.append(f"{k} : {v}")

    add("Titre", d["title"]); add("Sous-titre", d["subtitle"])
    add("Type d'événement", d["event_type"]["label"]); add("Présenté par", d["presenter_name"])
    add("Période", d["period"]); add("Dates et horaires", d["dates_text"]); add("Durée", d["duration"])
    add("Lieu", d["place"]["label"]); add("Type de public", d["audience"]); add("Tranche d'âge", d["age_group"])
    lines.append("")
    add("Description", "\n" + d["description_text"])
    lines.append("")
    for i in d["useful_information"]:
        add(f"Info pratique – {i['title'] or '(sans titre)'}", i["text"])
    for n, t in enumerate(d["ticket_office"], 1):
        add(f"Billetterie {n}", f"{t['title']} – {t['url']}")
    add("Visuels", d["visuals_url"]); add("Crédits", d["copyright"])
    add("Exposition liée", d["linked_event"]); add("À découvrir", " | ".join(d["associated_content"]))
    add("Message", d["message"])
    return "\n".join(lines)


def as_html(d):
    e = lambda v: html.escape(v or "")
    rows = []

    def add(k, v, raw=False):
        if v:
            rows.append(f'<tr><th align="left" valign="top" style="padding:6px 14px 6px 0;color:#5b645e;font-weight:normal;white-space:nowrap">{e(k)}</th>'
                        f'<td style="padding:6px 0">{v if raw else e(v).replace(chr(10), "<br>")}</td></tr>')

    add("Titre", d["title"]); add("Sous-titre", d["subtitle"])
    add("Type d'événement", d["event_type"]["label"]); add("Présenté par", d["presenter_name"])
    add("Période", d["period"]); add("Dates et horaires", d["dates_text"]); add("Durée", d["duration"])
    add("Lieu", d["place"]["label"]); add("Type de public", d["audience"]); add("Tranche d'âge", d["age_group"])
    add("Description", d["description"], raw=True)
    for i in d["useful_information"]:
        add(f"Info pratique – {i['title'] or '(sans titre)'}", i["text"])
    for n, t in enumerate(d["ticket_office"], 1):
        add(f"Billetterie {n}", f'{e(t["title"])} – <a href="{e(t["url"])}">{e(t["url"])}</a>', raw=True)
    add("Visuels", f'<a href="{e(d["visuals_url"])}">{e(d["visuals_url"])}</a>', raw=True)
    add("Crédits", d["copyright"]); add("Exposition liée", d["linked_event"])
    add("À découvrir", " | ".join(d["associated_content"])); add("Message", d["message"])
    return ('<div style="font-family:Arial,sans-serif;font-size:14px;color:#1c211e">'
            '<p>Nouvelle proposition d\'événement.</p><table cellspacing="0">' + "".join(rows) + "</table></div>")


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "evenement"


def send(d):
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    to = os.environ.get("MAIL_TO", "tphilipponneau@gmail.com")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))

    msg = EmailMessage()
    msg["Subject"] = f"[Agenda] {d['title']} – {d['period']}"[:200]
    msg["From"] = formataddr(("Contribution agenda", user))
    msg["To"] = to
    msg["Message-ID"] = make_msgid()
    msg.set_content("Nouvelle proposition d'événement.\n\n" + as_text(d))
    msg.add_alternative(as_html(d), subtype="html")
    msg.add_attachment(
        json.dumps(d, ensure_ascii=False, indent=2).encode("utf-8"),
        maintype="application", subtype="json",
        filename=f"{d['submitted_at'][:10]}-{slug(d['title'])}.json",
    )
    with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


class handler(BaseHTTPRequestHandler):
    def _reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self._reply(413, {"ok": False, "error": "Fiche vide ou trop volumineuse"})
        try:
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._reply(400, {"ok": False, "error": "Données illisibles"})

        if raw.get("website"):  # pot de miel anti-robots : on fait semblant d'accepter
            return self._reply(200, {"ok": True})

        d = normalize(raw)
        missing = validate(d)
        if missing:
            return self._reply(400, {"ok": False, "error": "Champs manquants : " + ", ".join(missing)})
        try:
            send(d)
        except KeyError:
            return self._reply(500, {"ok": False, "error": "Envoi d'e-mail non configuré"})
        except Exception:
            return self._reply(502, {"ok": False, "error": "Le serveur d'e-mail a refusé l'envoi"})
        return self._reply(200, {"ok": True})

    def do_GET(self):
        self._reply(405, {"ok": False, "error": "Utilisez POST"})
