import requests
import os
import platform
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from collections import defaultdict
from datetime import datetime


SITE_URL = "https://lakemichigancoffee.com"
CONSUMER_KEY = "ck_0c30e5d6e9f621cf6860208f8c4d4b80f8a5b628"
CONSUMER_SECRET = "cs_1b725e1d4f3221779ddb283247af847888f4235a"


def get_output_folder():
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop
    return Path.home()


def fetch_processing_orders():
    all_orders = []
    page = 1
    per_page = 100

    while True:
        url = f"{SITE_URL}/wp-json/wc/v3/orders"

        response = requests.get(
            url,
            auth=(CONSUMER_KEY, CONSUMER_SECRET),
            params={
                "status": "processing",
                "per_page": per_page,
                "page": page
            },
            timeout=30
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


def mark_order_completed(order_id):
    url = f"{SITE_URL}/wp-json/wc/v3/orders/{order_id}"

    response = requests.put(
        url,
        auth=(CONSUMER_KEY, CONSUMER_SECRET),
        json={"status": "completed"},
        timeout=30
    )

    response.raise_for_status()
    return response.json()


def clean_address(shipping):
    lines = []

    name = f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip()
    if name:
        lines.append(name)

    if shipping.get("company"):
        lines.append(shipping["company"])

    if shipping.get("address_1"):
        lines.append(shipping["address_1"])

    if shipping.get("address_2"):
        lines.append(shipping["address_2"])

    city_state_zip = f"{shipping.get('city', '')}, {shipping.get('state', '')} {shipping.get('postcode', '')}".strip()
    if city_state_zip and city_state_zip != ",":
        lines.append(city_state_zip)

    country = shipping.get("country")
    if country and country != "US":
        lines.append(country)

    return "\n".join(lines)


def get_item_options(item):
    options = []

    for meta in item.get("meta_data", []):
        key = meta.get("display_key") or meta.get("key")
        value = meta.get("display_value") or meta.get("value")

        if key and value and not str(key).startswith("_"):
            options.append(f"{key}: {value}")

    return options


def write_line(c, text, x, y, size=11, bold=False):
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, size)
    c.drawString(x, y, str(text))
    return y - 16


def write_wrapped_line(c, text, x, y, max_width, size=11, bold=False):
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


def create_pdf_report(orders):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = get_output_folder() / f"LakeMichiganCoffee_processing_orders_{timestamp}.pdf"

    c = canvas.Canvas(str(filename), pagesize=letter)
    width, height = letter

    x = 0.75 * inch
    right_margin = 0.75 * inch
    max_width = width - x - right_margin
    y = height - 0.75 * inch

    def new_page():
        nonlocal y
        c.showPage()
        y = height - 0.75 * inch

    y = write_line(c, "LAKE MICHIGAN COFFEE", x, y, 18, True)
    y = write_line(c, "Processing Orders Report", x, y, 14)
    y = write_line(c, f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}", x, y)
    y -= 12

    product_totals = defaultdict(int)

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

        y = write_wrapped_line(c, f"[ ] {quantity} x {product}", x, y, max_width)

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
            y = write_wrapped_line(c, line, x + 20, y, max_width - 20)

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
            y = write_wrapped_line(c, customer_note, x + 20, y, max_width - 20)

        y -= 10
        y = write_line(c, "Items:", x, y, 12, True)

        for item in order.get("line_items", []):
            if y < 0.75 * inch:
                new_page()

            quantity = int(item.get("quantity", 0))
            name = item.get("parent_name") or item.get("name") or "Unnamed item"

            y = write_wrapped_line(c, f"[ ] {quantity} x {name}", x + 20, y, max_width - 20, 12, True)

            for option in get_item_options(item):
                if y < 0.75 * inch:
                    new_page()
                y = write_wrapped_line(c, f"- {option}", x + 40, y, max_width - 40)

            y -= 6

    c.save()
    return filename


def open_pdf(filename):
    system = platform.system()

    if system == "Windows":
        os.startfile(filename)
    elif system == "Darwin":
        subprocess.run(["open", str(filename)], check=False)
    else:
        subprocess.run(["xdg-open", str(filename)], check=False)


class OrderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Lake Michigan Coffee Order Manager")
        self.root.geometry("460x285")
        self.root.resizable(False, False)

        self.orders = []

        title = tk.Label(
            root,
            text="Lake Michigan Coffee",
            font=("Arial", 20, "bold")
        )
        title.pack(pady=(20, 5))

        subtitle = tk.Label(
            root,
            text="Processing Order Manager",
            font=("Arial", 12)
        )
        subtitle.pack(pady=(0, 15))

        self.count_label = tk.Label(
            root,
            text="Loading processing orders...",
            font=("Arial", 14)
        )
        self.count_label.pack(pady=10)

        self.pdf_button = tk.Button(
            root,
            text="Get PDF of Processing Orders / Products",
            font=("Arial", 11),
            width=38,
            height=2,
            command=self.generate_pdf
        )
        self.pdf_button.pack(pady=8)

        self.complete_button = tk.Button(
            root,
            text="Mark All Processing Orders as Completed",
            font=("Arial", 11),
            width=38,
            height=2,
            command=self.complete_all_orders
        )
        self.complete_button.pack(pady=8)

        self.refresh_button = tk.Button(
            root,
            text="Refresh Order Count",
            font=("Arial", 10),
            command=self.load_orders
        )
        self.refresh_button.pack(pady=5)

        self.load_orders()

    def load_orders(self):
        try:
            self.count_label.config(text="Loading processing orders...")
            self.root.update_idletasks()

            self.orders = fetch_processing_orders()
            count = len(self.orders)

            self.count_label.config(text=f"Current processing orders: {count}")

        except Exception as e:
            self.count_label.config(text="Could not load orders.")
            messagebox.showerror("Error", f"Could not fetch orders:\n\n{e}")

    def generate_pdf(self):
        try:
            self.load_orders()

            if not self.orders:
                messagebox.showinfo("No Orders", "There are no processing orders.")
                return

            pdf_file = create_pdf_report(self.orders)
            open_pdf(pdf_file)

            messagebox.showinfo(
                "PDF Created",
                f"The processing orders PDF was created and opened.\n\nSaved to:\n{pdf_file}"
            )

        except Exception as e:
            messagebox.showerror("Error", f"Could not create PDF:\n\n{e}")

    def complete_all_orders(self):
        try:
            self.load_orders()

            if not self.orders:
                messagebox.showinfo("No Orders", "There are no processing orders to complete.")
                return

            count = len(self.orders)

            confirm = messagebox.askyesno(
                "Confirm Completion",
                f"Are you sure you want to mark all {count} processing orders as completed?\n\n"
                "Only do this after the orders have been packed."
            )

            if not confirm:
                return

            completed = 0

            for order in self.orders:
                order_id = order.get("id")

                if order_id is not None:
                    mark_order_completed(order_id)
                    completed += 1

            messagebox.showinfo(
                "Done",
                f"Marked {completed} orders as completed."
            )

            self.load_orders()

        except Exception as e:
            messagebox.showerror("Error", f"Could not complete orders:\n\n{e}")


def main():
    root = tk.Tk()

    if platform.system() == "Darwin":
        try:
            root.createcommand("tk::mac::ReopenApplication", root.deiconify)
        except Exception:
            pass

    OrderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
