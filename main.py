import json
import os
import uuid
from pathlib import Path

import cv2
import flet as ft
import flet_camera as fc
import flet_permission_handler as fph
import requests


_storage_root = os.environ.get("FLET_APP_STORAGE_DATA")
if not _storage_root:
    raise RuntimeError(
        "FLET_APP_STORAGE_DATA is not available. "
        "The app must be packaged/run by Flet."
    )

APP_DIR = Path(_storage_root) / ".ims_mobile"
APP_DIR.mkdir(parents=True, exist_ok=True)

QUEUE_FILE = APP_DIR / "pending_operations.json"
CONFIG_FILE = APP_DIR / "config.json"


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_barcode_detector():
    try:
        if hasattr(cv2, "barcode") and hasattr(
            cv2.barcode, "BarcodeDetector"
        ):
            return cv2.barcode.BarcodeDetector()
    except Exception:
        pass
    return None


def decode_barcodes_from_image(image_bytes):
    try:
        detector = create_barcode_detector()
        if detector is None:
            return None

        import numpy as np

        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            return None

        if hasattr(detector, "detectAndDecodeWithType"):
            result = detector.detectAndDecodeWithType(image)
            if isinstance(result, tuple) and len(result) >= 2:
                decoded_info = result[1]
                if decoded_info:
                    for value in decoded_info:
                        if value:
                            return str(value).strip()

        if hasattr(detector, "detectAndDecode"):
            result = detector.detectAndDecode(image)
            decoded_info = result[0] if isinstance(result, tuple) else result
            if isinstance(decoded_info, (list, tuple)):
                for value in decoded_info:
                    if value:
                        return str(value).strip()
            elif decoded_info:
                return str(decoded_info).strip()
    except Exception:
        return None

    return None


def main(page: ft.Page):
    page.title = "IMS Mobile"
    page.rtl = True
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    config = load_json(
        CONFIG_FILE,
        {"api_url": "http://192.168.1.100:5000", "token": ""},
    )
    queue = load_json(QUEUE_FILE, [])

    api_url = ft.TextField(
        label="آدرس سرور PC",
        value=config.get("api_url", ""),
        rtl=False,
    )
    token = ft.TextField(
        label="توکن (اختیاری)",
        value=config.get("token", ""),
        password=True,
        rtl=False,
    )
    status = ft.Text("آماده", color=ft.Colors.GREEN)
    barcode = ft.TextField(label="بارکد کالا", autofocus=True, rtl=False)
    product_info = ft.Text("هنوز کالایی انتخاب نشده")
    qty = ft.TextField(
        label="تعداد",
        value="1",
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    unit = ft.Dropdown(
        label="واحد",
        value="تکی",
        options=[ft.dropdown.Option("تکی"), ft.dropdown.Option("کارتن")],
    )
    movement_type = ft.Dropdown(
        label="نوع عملیات",
        value="ورود",
        options=[ft.dropdown.Option("ورود"), ft.dropdown.Option("خروج")],
    )
    price = ft.TextField(
        label="قیمت",
        value="0",
        keyboard_type=ft.KeyboardType.NUMBER,
    )
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
            response = api_get("/api/v1/health")
            data = response.json()
            status.value = (
                "اتصال برقرار است ✅"
                if response.ok and data.get("success")
                else "پاسخ نامعتبر"
            )
            status.color = ft.Colors.GREEN if response.ok else ft.Colors.RED
        except Exception:
            status.value = "اتصال برقرار نشد؛ اطلاعات آفلاین ذخیره می‌شود."
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
            permission = await ph.request(fph.Permission.CAMERA)
            if permission is not None and permission != fph.PermissionStatus.GRANTED:
                status.value = "دسترسی دوربین داده نشد."
                page.update()
                return

            cameras = await camera.get_available_cameras()
            if not cameras:
                status.value = "دوربین گوشی پیدا نشد."
                page.update()
                return

            back = next(
                (item for item in cameras if item.lens_direction.value == "back"),
                cameras[0],
            )

            if not camera_state["initialized"]:
                await camera.initialize(
                    back,
                    fc.ResolutionPreset.HIGH,
                    enable_audio=False,
                )
                camera_state["initialized"] = True
                camera_state["description"] = back

            scanner_status.value = (
                "دوربین روشن است؛ بارکد را مقابل دوربین بگیرید و دکمه خواندن را بزنید."
            )
            dialog.open = True
            page.update()
        except Exception as exc:
            status.value = f"خطای دوربین: {exc}"
            page.update()

    async def capture_and_decode(_=None):
        try:
            image_bytes = await camera.take_picture()
            if not image_bytes:
                scanner_status.value = "تصویر دوربین دریافت نشد."
                page.update()
                return

            code = decode_barcodes_from_image(image_bytes)
            if code:
                dialog.open = False
                use_scanned_code(code)
            else:
                scanner_status.value = (
                    "بارکدی پیدا نشد؛ گوشی را کمی نزدیک/دور کنید و دوباره امتحان کنید."
                )
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
            response = api_get(f"/api/v1/products/barcode/{code}")
            data = response.json()
            if response.ok and data.get("success"):
                selected_product["value"] = data["product"]
                product = data["product"]
                product_info.value = (
                    f"{product.get('name', '')} | موجودی: "
                    f"تکی {product.get('single_stock', 0)} / "
                    f"کارتن {product.get('carton_stock', 0)}"
                )
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
        product = selected_product["value"]
        if not product:
            status.value = "ابتدا کالا را با بارکد پیدا کنید."
            page.update()
            return

        try:
            quantity = int(qty.value)
            item_price = float(price.value or 0)
        except (ValueError, TypeError):
            status.value = "تعداد یا قیمت نامعتبر است."
            page.update()
            return

        operation = {
            "operation_id": str(uuid.uuid4()),
            "product_id": int(product["id"]),
            "movement_type": movement_type.value,
            "quantity": quantity,
            "unit_type": unit.value,
            "price": item_price,
            "description": description.value or "",
        }

        try:
            response = api_post("/api/v1/movements", operation)
            data = response.json()
            if response.ok and data.get("success"):
                status.value = "عملیات ثبت شد و موجودی PC به‌روز شد ✅"
            else:
                status.value = data.get("message", "ثبت ناموفق بود")
        except Exception:
            queue_operation(operation)
            status.value = (
                "اینترنت/سرور قطع است؛ عملیات در گوشی ذخیره شد و بعداً ارسال می‌شود."
            )
        page.update()

    def sync_queue(_=None):
        if not queue:
            status.value = "عملیات معوقی وجود ندارد."
            page.update()
            return

        payload = {
            "device_id": "android-" + str(uuid.getnode()),
            "operations": queue,
        }

        try:
            response = api_post("/api/v1/sync/push", payload)
            data = response.json()
            if not response.ok or not data.get("success"):
                status.value = data.get("message", "همگام‌سازی ناموفق بود")
                page.update()
                return

            applied_ids = {
                item["operation_id"]
                for item in data.get("results", [])
                if item.get("status") in ("applied", "already_applied")
            }

            queue[:] = [
                item
                for item in queue
                if item.get("operation_id") not in applied_ids
            ]
            save_json(QUEUE_FILE, queue)
            status.value = (
                "همگام‌سازی انجام شد؛ "
                f"{len(applied_ids)} عملیات ارسال شد."
            )
        except Exception:
            status.value = "سرور در دسترس نیست؛ عملیات در صف باقی ماند."
        page.update()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("اسکن بارکد"),
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Container(content=camera, height=360, width=330),
                    scanner_status,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=340,
        ),
        actions=[
            ft.TextButton("خواندن بارکد", on_click=capture_and_decode),
            ft.TextButton("بستن", on_click=close_scanner),
        ],
    )
    page.overlay.append(dialog)

    settings = ft.Column(
        [
            ft.Text("اتصال به PC", size=20, weight=ft.FontWeight.BOLD),
            api_url,
            token,
            ft.Row(
                [
                    ft.ElevatedButton("ذخیره", on_click=save_config),
                    ft.ElevatedButton("تست اتصال", on_click=check_connection),
                ]
            ),
        ]
    )

    movement = ft.Column(
        [
            ft.Text("ثبت ورود / خروج", size=20, weight=ft.FontWeight.BOLD),
            ft.Row(
                [
                    barcode,
                    ft.ElevatedButton("جستجو", on_click=find_product),
                    ft.ElevatedButton("📷 اسکن بارکد", on_click=open_scanner),
                ]
            ),
            product_info,
            movement_type,
            unit,
            qty,
            price,
            description,
            ft.Row(
                [
                    ft.ElevatedButton("ثبت عملیات", on_click=add_movement),
                    ft.ElevatedButton(
                        "همگام‌سازی عملیات معوق",
                        on_click=sync_queue,
                    ),
                ]
            ),
        ]
    )

    page.add(settings, ft.Divider(), movement, ft.Divider(), status)


if __name__ == "__main__":
    ft.run(main)
