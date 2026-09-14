import json
import os
import uuid
from pathlib import Path

import flet as ft
import requests

import flet_camera as fc
import flet_permission_handler as fph

try:
    from pyzbar.pyzbar import decode as decode_barcodes
    from PIL import Image
    import io
except Exception:
    decode_barcodes = None

APP_DIR = Path(ft.app_storage_path() or Path.home() / ".ims_mobile")
APP_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_FILE = APP_DIR / "pending_operations.json"
CONFIG_FILE = APP_DIR / "config.json"


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main(page: ft.Page):
    page.title = "IMS Mobile"
    page.rtl = True
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    config = load_json(CONFIG_FILE, {"api_url": "http://192.168.1.100:5000", "token": ""})
    queue = load_json(QUEUE_FILE, [])

    api_url = ft.TextField(label="آدرس سرور PC", value=config.get("api_url", ""), text_direction=ft.TextDirection.LTR)
    token = ft.TextField(label="توکن (اختیاری)", value=config.get("token", ""), password=True, text_direction=ft.TextDirection.LTR)
    status = ft.Text("آماده", color=ft.Colors.GREEN)
    barcode = ft.TextField(label="بارکد کالا", autofocus=True, text_direction=ft.TextDirection.LTR)
    product_info = ft.Text("هنوز کالایی انتخاب نشده")
    qty = ft.TextField(label="تعداد", value="1", keyboard_type=ft.KeyboardType.NUMBER)
    unit = ft.Dropdown(label="واحد", value="تکی", options=[ft.dropdown.Option("تکی"), ft.dropdown.Option("کارتن")])
    movement_type = ft.Dropdown(label="نوع عملیات", value="ورود", options=[ft.dropdown.Option("ورود"), ft.dropdown.Option("خروج")])
    price = ft.TextField(label="قیمت", value="0", keyboard_type=ft.KeyboardType.NUMBER)
    description = ft.TextField(label="توضیحات", multiline=True)

    selected_product = {"value": None}
    camera = fc.Camera(preview_enabled=True, expand=True)
    camera_state = {"initialized": False, "description": None}
    scanner_status = ft.Text("آماده اسکن", color=ft.Colors.WHITE)
    ph = fph.PermissionHandler()

    def headers():
        h = {}
        if token.value.strip():
            h["X-IMS-Token"] = token.value.strip()
        return h

    def base_url():
        return api_url.value.strip().rstrip("/")

    def save_config(_=None):
        save_json(CONFIG_FILE, {"api_url": base_url(), "token": token.value.strip()})
        status.value = "تنظیمات ذخیره شد"
        page.update()

    def api_get(path, params=None):
        return requests.get(base_url() + path, headers=headers(), params=params, timeout=5)

    def api_post(path, payload):
        return requests.post(base_url() + path, headers=headers(), json=payload, timeout=7)

    def check_connection(_=None):
        save_config()
        try:
            r = api_get("/api/v1/health")
            data = r.json()
            status.value = "اتصال برقرار است ✅" if r.ok and data.get("success") else "پاسخ نامعتبر"
            status.color = ft.Colors.GREEN if r.ok else ft.Colors.RED
        except Exception as exc:
            status.value = f"اتصال برقرار نشد؛ اطلاعات آفلاین ذخیره می‌شود."
            status.color = ft.Colors.ORANGE
        page.update()

    def use_scanned_code(code):
        code = (code or "").strip()
        if not code:
            return
        barcode.value = code
        status.value = f"بارکد خوانده شد: {code}"
        page.update()
        find_product()

    async def open_scanner(_=None):
        try:
            perm = await ph.request(fph.Permission.CAMERA)
            if perm is not None and perm != fph.PermissionStatus.GRANTED:
                status.value = "دسترسی دوربین داده نشد."
                page.update()
                return
            cameras = await camera.get_available_cameras()
            if not cameras:
                status.value = "دوربین گوشی پیدا نشد."
                page.update()
                return
            back = next((c for c in cameras if c.lens_direction.value == "back"), cameras[0])
            if not camera_state["initialized"]:
                await camera.initialize(back, fc.ResolutionPreset.HIGH, enable_audio=False)
                camera_state["initialized"] = True
                camera_state["description"] = back
            scanner_status.value = "دوربین روشن است؛ بارکد را مقابل دوربین بگیرید و دکمه خواندن را بزنید."
            dialog.open = True
            page.update()
        except Exception as exc:
            status.value = f"خطای دوربین: {exc}"
            page.update()

    async def capture_and_decode(_=None):
        if decode_barcodes is None:
            scanner_status.value = "ماژول بارکدخوان در این محیط نصب نیست؛ بارکد را دستی وارد کنید."
            page.update()
            return
        try:
            image_bytes = await camera.take_picture()
            results = decode_barcodes(Image.open(io.BytesIO(image_bytes)))
            if results:
                code = results[0].data.decode("utf-8", errors="ignore")
                dialog.open = False
                use_scanned_code(code)
            else:
                scanner_status.value = "بارکدی پیدا نشد؛ گوشی را کمی نزدیک/دور کنید و دوباره امتحان کنید."
            page.update()
        except Exception as exc:
            scanner_status.value = f"خواندن بارکد ناموفق بود: {exc}"
            page.update()

    async def close_scanner(_=None):
        dialog.open = False
        page.update()

    def find_product(_=None):
        code = barcode.value.strip()
        if not code:
            return
        try:
            r = api_get(f"/api/v1/products/barcode/{code}")
            data = r.json()
            if r.ok and data.get("success"):
                selected_product["value"] = data["product"]
                p = data["product"]
                product_info.value = f"{p.get('name','')} | موجودی: تکی {p.get('single_stock',0)} / کارتن {p.get('carton_stock',0)}"
                status.value = "کالا پیدا شد ✅"
            else:
                selected_product["value"] = None
                product_info.value = data.get("message", "کالا پیدا نشد")
        except Exception:
            selected_product["value"] = None
            product_info.value = "سرور در دسترس نیست؛ ابتدا اتصال را بررسی کنید."
        page.update()

    def queue_operation(operation):
        queue.append(operation)
        save_json(QUEUE_FILE, queue)

    def add_movement(_=None):
        p = selected_product["value"]
        if not p:
            status.value = "ابتدا کالا را با بارکد پیدا کنید."
            page.update()
            return
        try:
            q = int(qty.value)
            pr = float(price.value or 0)
        except ValueError:
            status.value = "تعداد یا قیمت نامعتبر است."
            page.update()
            return
        op = {
            "operation_id": str(uuid.uuid4()),
            "product_id": int(p["id"]),
            "movement_type": movement_type.value,
            "quantity": q,
            "unit_type": unit.value,
            "price": pr,
            "description": description.value or "",
        }
        try:
            r = api_post("/api/v1/movements", op)
            data = r.json()
            if r.ok and data.get("success"):
                status.value = "عملیات ثبت شد و موجودی PC به‌روز شد ✅"
            else:
                status.value = data.get("message", "ثبت ناموفق بود")
        except Exception:
            queue_operation(op)
            status.value = "اینترنت/سرور قطع است؛ عملیات در گوشی ذخیره شد و بعداً ارسال می‌شود."
        page.update()

    def sync_queue(_=None):
        if not queue:
            status.value = "عملیات معوقی وجود ندارد."
            page.update()
            return
        payload = {"device_id": "android-" + uuid.getnode().__str__(), "operations": queue}
        try:
            r = api_post("/api/v1/sync/push", payload)
            data = r.json()
            if not r.ok or not data.get("success"):
                status.value = data.get("message", "همگام‌سازی ناموفق بود")
                page.update()
                return
            applied_ids = {x["operation_id"] for x in data.get("results", []) if x.get("status") in ("applied", "already_applied")}
            queue[:] = [x for x in queue if x.get("operation_id") not in applied_ids]
            save_json(QUEUE_FILE, queue)
            status.value = f"همگام‌سازی انجام شد؛ {len(applied_ids)} عملیات ارسال شد."
        except Exception:
            status.value = "سرور در دسترس نیست؛ عملیات در صف باقی ماند."
        page.update()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("اسکن بارکد"),
        content=ft.Container(
            content=ft.Column([
                ft.Container(content=camera, height=360, width=330),
                scanner_status,
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=340,
        ),
        actions=[
            ft.TextButton("خواندن بارکد", on_click=capture_and_decode),
            ft.TextButton("بستن", on_click=close_scanner),
        ],
    )
    page.overlay.append(dialog)

    settings = ft.Column([
        ft.Text("اتصال به PC", size=20, weight=ft.FontWeight.BOLD),
        api_url,
        token,
        ft.Row([ft.ElevatedButton("ذخیره", on_click=save_config), ft.ElevatedButton("تست اتصال", on_click=check_connection)]),
    ])

    movement = ft.Column([
        ft.Text("ثبت ورود / خروج", size=20, weight=ft.FontWeight.BOLD),
        ft.Row([barcode, ft.ElevatedButton("جستجو", on_click=find_product), ft.ElevatedButton("📷 اسکن بارکد", on_click=open_scanner)]),
        product_info,
        movement_type,
        unit,
        qty,
        price,
        description,
        ft.Row([ft.ElevatedButton("ثبت عملیات", on_click=add_movement), ft.ElevatedButton("همگام‌سازی عملیات معوق", on_click=sync_queue)]),
    ])

    page.add(settings, ft.Divider(), movement, ft.Divider(), status)


if __name__ == "__main__":
    ft.app(target=main)
