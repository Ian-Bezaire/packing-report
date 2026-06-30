import json
import os
import platform
import subprocess
import sys
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Any, Dict, List, Optional

import requests
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

SITE_URL = "https://lakemichigancoffee.com"
APP_NAME = "Lake Michigan Coffee Order Manager"
CONFIG_FILE_NAME = "config.json"


def app_data_dir() -> Path:
    """Return a writable per-user app data folder for macOS, Windows, or Linux."""
    system = platform.system()

    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    path = base / "LakeMichiganOrderManager"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / CONFIG_FILE_NAME


def default_pdf_dir() -> Path:
    """Use Desktop when it exists; otherwise use the user's home folder."""
    desktop = Path.home() / "Desktop"
    return desktop if desktop.exists() else Path.home()


def load_config() -> Dict[str, str]:
    """Load API credentials from env vars first, then local config file."""
    config: Dict[str, str] = {
        "site_url": os.environ.get("LMC_SITE_URL", SITE_URL),
        "consumer_key": os.environ.get("LMC_CONSUMER_KEY", ""),
        "consumer_secret": os.environ.get("LMC_CONSUMER_SECRET", ""),
    }

    path = config_path()
    if path.exists():
        try:
            file_config = json.loads(path.read_text(encoding="utf-8"))
            for key in ("site_url", "consumer_key", "consumer_secret"):
                if not config.get(key) and file_config.get(key):
                    config[key] = str(file_config[key])
                elif key == "site_url" and file_config.get(key) and not os.environ.get("LMC_SITE_URL"):
                    config[key] = str(file_config[key])
        except Exception:
            # If config is corrupt, the app will prompt again.
            pass

    return config


def save_config(site_url: str, consumer_key: str, consumer_secret: str) -> None:
    data = {
        "site_url": site_url.strip().rstrip("/"),
        "consumer_key": consumer_key.strip(),
        "consumer_secret": consumer_secret.strip(),
    }
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def require_config(root: tk.Tk, force_edit: bool = False) -> Optional[Dict[str, str]]:
    """Ensure credentials exist, prompting the user if needed."""
    config = load_config()

    if (
        not force_edit
        and config.get("site_url")
        and config.get("consumer_key")
        and config.get("consumer_secret")
    ):
        return config

    messagebox.showinfo(
        "Setup Needed",
        "Enter the WooCommerce REST API credentials once. They will be saved locally on this Mac.",
        parent=root,
    )

    site_url = simpledialog.askstring(
        "Store URL",
        "Store URL:",
        initialvalue=config.get("site_url") or SITE_URL,
        parent=root,
    )
    if not site_url:
        return None

    consumer_key = simpledialog.askstring(
        "WooCommerce Consumer Key",
        "Consumer Key:",
        initialvalue=config.get("consumer_key", ""),
        parent=root,
    )
    if not consumer_key:
        return None

    consumer_secret = simpledialog.askstring(
        "WooCommerce Consumer Secret",
        "Consumer Secret:",
        initialvalue=config.get("consumer_secret", ""),
        show="*",
        parent=root,
    )
    if not consumer_secret:
        return None

    save_config(site_url, consumer_key, consumer_secret)
    return load_config()


def fetch_processing_orders(config: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetch all processing orders, paging past WooCommerce's 100-order limit."""
    all_orders: List[Dict[str, Any]] = []
    page = 1
    per_page = 100
    site_url = config["site_url"].rstrip("/")

    while True:
        url = f"{site_url}/wp-json/wc/v3/orders"
        response = requests.get(
            url,
            auth=(config["consumer_key"], config["consumer_secret"]),
            params={"status": "processing", "per_page": per_page, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        orders = response.json()
        if not orders:
            break

        all_orders.extend(orders)
        if len(orders) < per_page:
            break
        page += 1

    return all_orders


def mark_order_completed(config: Dict[str, str], order_id: int) -> Dict[str, Any]:
    site_url = config["site_url"].rstrip("/")
    url = f"{site_url}/wp-json/wc/v3/orders/{order_id}"
    response = requests.put(
        url,
        auth=(config["consumer_key"], config["consumer_secret"]),
        json={"status": "completed"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def clean_address(shipping: Dict[str, Any]) -> str:
    lines: List[str] = []

    name = f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip()
    if name:
        lines.append(name)

    for key in ("company", "address_1", "address_2"):
        value = shipping.get(key)
        if value:
            lines.append(str(value))

    city = shipping.get("city", "")
    state = shipping.get("state", "")
    postcode = shipping.get("postcode", "")
    city_state_zip = f"{city}, {state} {postcode}".strip()
    if city_state_zip and city_state_zip != ",":
        lines.append(city_state_zip)

    country = shipping.get("country")
    if country and country != "US":
        lines.append(str(country))

    return "\n".join(lines)


def get_item_options(item: Dict[str, Any]) -> List[str]:
    options: List[str] = []

    for meta in item.get("meta_data", []):
        key = meta.get("display_key") or meta.get("key")
        value = meta.get("display_value") or meta.get("value")

        if key and value and not str(key).startswith("_"):
            options.append(f"{key}: {value}")

    return options


def draw_wrapped_line(c: canvas.Canvas, text: str, x: float, y: float, max_width: float, size: int = 11, bold: bool = False) -> float:
    """Draw text with simple word wrapping and return the next y position."""
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, size)

    words = str(text).split()
    if not words:
        return y - 16

    line = ""
    for word in words:
        test_line = word if not line else f"{line} {word}"
        if c.stringWidth(test_line, font, size) <= max_width:
            line = test_line
        else:
            c.drawString(x, y, line)
            y -= 16
            line = word

    if line:
        c.drawString(x, y, line)
        y -= 16

    return y


def write_line(c: canvas.Canvas, text: str, x: float, y: float, size: int = 11, bold: bool = False) -> float:
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, size)
    c.drawString(x, y, str(text))
    return y - 16


def create_pdf_report(orders: List[Dict[str, Any]], filename: Optional[Path] = None) -> Path:
    if filename is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = default_pdf_dir() / f"LakeMichiganCoffee_processing_orders_{timestamp}.pdf"

    c = canvas.Canvas(str(filename), pagesize=letter)
    width, height = letter

    x = 0.75 * inch
    right_margin = 0.75 * inch
    max_width = width - x - right_margin
    y = height - 0.75 * inch

    def new_page() -> None:
        nonlocal y
        c.showPage()
        y = height - 0.75 * inch

    y = write_line(c, "LAKE MICHIGAN COFFEE", x, y, 18, True)
    y = write_line(c, "Processing Orders Report", x, y, 14)
    y = write_line(c, f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}", x, y)
    y -= 12

    product_totals: defaultdict[str, int] = defaultdict(int)

    for order in orders:
        for item in order.get("line_items", []):
            name = item.get("parent_name") or item.get("name") or "Unnamed item"
            quantity = int(item.get("quantity", 0))
            options = get_item_options(item)

            product_name = str(name)
            if options:
                product_name += " - " + ", ".join(options)

            product_totals[product_name] += quantity

    y = write_line(c, "TOTAL PRODUCT REPORT", x, y, 14, True)
    y -= 6

    for product, quantity in sorted(product_totals.items()):
        if y < 0.75 * inch:
            new_page()
        y = draw_wrapped_line(c, f"[ ] {quantity} x {product}", x, y, max_width)

    for order in orders:
        new_page()

        order_number = order.get("number", order.get("id"))
        billing = order.get("billing", {})
        shipping = order.get("shipping", {})

        customer_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()

        y = write_line(c, f"ORDER #{order_number}", x, y, 18, True)
        y -= 8

        y = write_line(c, f"Customer: {customer_name}", x, y, 12, True)
        y -= 6

        y = write_line(c, "Ship To:", x, y, 12, True)

        for line in clean_address(shipping).split("\n"):
            if y < 0.75 * inch:
                new_page()
            y = draw_wrapped_line(c, line, x + 20, y, max_width - 20)

        phone = shipping.get("phone") or billing.get("phone")
        if phone:
            y -= 6
            y = write_line(c, f"Phone: {phone}", x, y)

        email = billing.get("email")
        if email:
            y = write_line(c, f"Email: {email}", x, y)

        customer_note = order.get("customer_note")
        if customer_note:
            y -= 10
            y = write_line(c, "CUSTOMER NOTE:", x, y, 12, True)
            y = draw_wrapped_line(c, customer_note, x + 20, y, max_width - 20)

        y -= 10
        y = write_line(c, "Items:", x, y, 12, True)

        for item in order.get("line_items", []):
            if y < 0.75 * inch:
                new_page()
            quantity = int(item.get("quantity", 0))
            name = item.get("parent_name") or item.get("name") or "Unnamed item"

            y = draw_wrapped_line(c, f"[ ] {quantity} x {name}", x + 20, y, max_width - 20, 12, True)

            for option in get_item_options(item):
                if y < 0.75 * inch:
                    new_page()
                y = draw_wrapped_line(c, f"- {option}", x + 40, y, max_width - 40)

            y -= 6

    c.save()
    return filename


def open_pdf(filename: Path) -> None:
    system = platform.system()

    if system == "Windows":
        os.startfile(filename)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.run(["open", str(filename)], check=False)
    else:
        subprocess.run(["xdg-open", str(filename)], check=False)


class OrderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("460x315")
        self.root.resizable(False, False)

        self.config: Optional[Dict[str, str]] = None
        self.orders: List[Dict[str, Any]] = []

        title = tk.Label(root, text="Lake Michigan Coffee", font=("Arial", 20, "bold"))
        title.pack(pady=(18, 5))

        subtitle = tk.Label(root, text="Processing Order Manager", font=("Arial", 12))
        subtitle.pack(pady=(0, 14))

        self.count_label = tk.Label(root, text="Loading processing orders...", font=("Arial", 14))
        self.count_label.pack(pady=8)

        self.pdf_button = tk.Button(
            root,
            text="Get PDF of Processing Orders / Products",
            font=("Arial", 11),
            width=38,
            height=2,
            command=self.generate_pdf,
        )
        self.pdf_button.pack(pady=6)

        self.complete_button = tk.Button(
            root,
            text="Mark All Processing Orders as Completed",
            font=("Arial", 11),
            width=38,
            height=2,
            command=self.complete_all_orders,
        )
        self.complete_button.pack(pady=6)

        button_frame = tk.Frame(root)
        button_frame.pack(pady=7)

        self.refresh_button = tk.Button(button_frame, text="Refresh Order Count", font=("Arial", 10), command=self.load_orders)
        self.refresh_button.grid(row=0, column=0, padx=5)

        self.settings_button = tk.Button(button_frame, text="Settings", font=("Arial", 10), command=self.edit_settings)
        self.settings_button.grid(row=0, column=1, padx=5)

        self.load_orders()

    def ensure_config(self, force_edit: bool = False) -> bool:
        config = require_config(self.root, force_edit=force_edit)
        if not config:
            self.count_label.config(text="Setup needed.")
            return False
        self.config = config
        return True

    def edit_settings(self) -> None:
        if self.ensure_config(force_edit=True):
            messagebox.showinfo("Settings Saved", "Credentials were saved locally.")
            self.load_orders()

    def load_orders(self) -> None:
        if not self.ensure_config():
            return

        try:
            self.count_label.config(text="Loading processing orders...")
            self.root.update_idletasks()
            self.orders = fetch_processing_orders(self.config)
            count = len(self.orders)
            self.count_label.config(text=f"Current processing orders: {count}")
        except Exception as e:
            self.count_label.config(text="Could not load orders.")
            messagebox.showerror("Error", f"Could not fetch orders:\n\n{e}")

    def generate_pdf(self) -> None:
        try:
            self.load_orders()

            if not self.orders:
                messagebox.showinfo("No Orders", "There are no processing orders.")
                return

            pdf_file = create_pdf_report(self.orders)
            open_pdf(pdf_file)

            messagebox.showinfo("PDF Created", f"The processing orders PDF was created:\n\n{pdf_file}")

        except Exception as e:
            messagebox.showerror("Error", f"Could not create PDF:\n\n{e}")

    def complete_all_orders(self) -> None:
        try:
            self.load_orders()

            if not self.orders:
                messagebox.showinfo("No Orders", "There are no processing orders to complete.")
                return

            count = len(self.orders)

            confirm = messagebox.askyesno(
                "Confirm Completion",
                f"Are you sure you want to mark all {count} processing orders as completed?\n\n"
                "Only do this after the orders have been packed.",
            )

            if not confirm:
                return

            completed = 0

            for order in self.orders:
                order_id = order.get("id")
                if order_id is not None:
                    mark_order_completed(self.config, int(order_id))
                    completed += 1

            messagebox.showinfo("Done", f"Marked {completed} orders as completed.")
            self.load_orders()

        except Exception as e:
            messagebox.showerror("Error", f"Could not complete orders:\n\n{e}")


def main() -> None:
    root = tk.Tk()

    # Make app naming look nicer in macOS menu bar when possible.
    if platform.system() == "Darwin":
        try:
            root.createcommand("tk::mac::ReopenApplication", root.deiconify)
        except Exception:
            pass

    OrderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
