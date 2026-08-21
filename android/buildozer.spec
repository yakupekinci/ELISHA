[app]
title = ELİŞA
package.name = elisha
package.domain = com.elisha.voice
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,yaml,onnx,json
version = 0.1
version.regex = __version__ = ['"]([^'"]*)['"]
version.filename = %(source.dir)s/../elisha/__init__.py
requirements = python3,kivy==2.3.0,pyyaml,requests,numpy,duckduckgo-search
# Not: tam offline STT/LLM/TTS için V2'de ekle:
# requirements = ...,faster-whisper,openwakeword,piper-tts,sherpa-onnx,llama-cpp-python
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,RECORD_AUDIO,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license_agreement = True
android.ant = auto
p4a.branch = master
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1

# Docker ile build için:
# docker run --rm -v "$PWD":/home/user/hostcwd kivy/buildozer -v android debug
