[app]
title = Tro Ly Ao
package.name = troly
package.domain = org.liam
source.dir = .
source.include_exts = py
version = 1.0
requirements = python3,kivy==2.3.1,certifi
orientation = portrait
fullscreen = 0

android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 0
