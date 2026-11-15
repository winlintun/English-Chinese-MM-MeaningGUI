[app]
title = VocApp
package.name = VocApp
package.domain = org.VocApp
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,qml,js,ttf,otf,db
version = 0.1
requirements = python3,shiboken6,PySide6
orientation = portrait
osx.kivy_version = 2.2.0
fullscreen = 0
android.archs = arm64-v8a
android.allow_backup = True
ios.kivy_ios_url = https://github.com/kivy/kivy-ios
ios.kivy_ios_branch = master
ios.ios_deploy_url = https://github.com/phonegap/ios-deploy
ios.ios_deploy_branch = 1.12.2
ios.codesign.allowed = false
android.ndk_path = /home/winlintun/.pyside6_android_deploy/android-ndk/android-ndk-r28c
android.api = 35
android.minapi = 28
android.ndk_api = 28
android.no-byte-compile-python = True
p4a.bootstrap = qt
p4a.local_recipes = /home/winlintun/Desktop/English-Chinese-MM-MeaningGUI/deployment/recipes
p4a.branch = master
p4a.commit = 58d21141f17c889bf8585f5665921d72028f8831
android.permissions = android.permission.BLUETOOTH, android.permission.MODIFY_AUDIO_SETTINGS, android.permission.CAMERA, android.permission.RECORD_AUDIO, android.permission.WRITE_EXTERNAL_STORAGE, android.permission.INTERNET, android.permission.ACCESS_NETWORK_STATE
android.add_jars = /home/winlintun/Desktop/English-Chinese-MM-MeaningGUI/deployment/jar/PySide6/jar/Qt6Android.jar,/home/winlintun/Desktop/English-Chinese-MM-MeaningGUI/deployment/jar/PySide6/jar/Qt6AndroidMultimedia.jar,/home/winlintun/Desktop/English-Chinese-MM-MeaningGUI/deployment/jar/PySide6/jar/Qt6AndroidBindings.jar,/home/winlintun/Desktop/English-Chinese-MM-MeaningGUI/deployment/jar/PySide6/jar/Qt6AndroidNetworkInformationBackend.jar,/home/winlintun/Desktop/English-Chinese-MM-MeaningGUI/deployment/jar/PySide6/jar/Qt6AndroidNetwork.jar
p4a.extra_args = --qt-libs=Multimedia,Core,Network,Widgets,Concurrent,Gui --load-local-libs=Qt6FFmpegStub-crypto,plugins_multimedia_ffmpegmediaplugin,avcodec,swscale,avformat,avutil,Qt6FFmpegStub-ssl,plugins_platforms_qtforandroid,swresample,plugins_multimedia_androidmediaplugin --init-classes=
icon.filename = /home/winlintun/Desktop/English-Chinese-MM-MeaningGUI/.env/lib/python3.12/site-packages/PySide6/scripts/deploy_lib/pyside_icon.jpg

[buildozer]
log_level = 2
warn_on_root = 1
bin_dir = /home/winlintun/Desktop/English-Chinese-MM-MeaningGUI

