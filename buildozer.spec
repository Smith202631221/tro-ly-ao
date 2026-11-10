[app]
title = Tro Ly Ao
package.name = troly
package.domain = org.liam
source.dir = .
source.include_exts = py
version = 1.0
requirements = python3,kivy==2.3.0,certifi,pillow,fpdf2==2.9.0,fonttools,openpyxl,et_xmlfile,pypdf
orientation = portrait
fullscreen = 0

android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
# Cho phép gọi Ollama qua http://127.0.0.1 (Android 9+ chặn http mặc định)
android.extra_manifest_application_arguments = ./extra_manifest_application_arguments.xml
# Cho phép tìm dịch vụ đọc/nhận giọng nói (Android 11+)
android.extra_manifest_xml = ./extra_manifest.xml

# Dùng bản python-for-android ổn định (bản mới nhất đang lỗi khi cài thư viện)
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 0
