#!/usr/bin/env python3
"""Compile the real upstream aspect-setting method into a focused contract harness."""
import re
from pathlib import Path
import subprocess
import sys
source=Path(sys.argv[1]).read_text()
a=source.index('void PlayerComponent::updateVideoAspectSettings()')
b=source.index('void PlayerComponent::updateVideoConfiguration()',a)
method=source[a:b]
harness=r'''
#include <QVariant>
#include <QString>
#include <QMap>
#include <cassert>
#include <cmath>
#include <cstdio>
static QString chosen;
static constexpr int SETTINGS_SECTION_VIDEO=0;
struct SettingsComponent {
 static SettingsComponent& Get() {static SettingsComponent s;return s;}
 QVariant value(int,const char*) {return chosen;}
};
struct Mpv {
 QMap<QString,QVariant> values;
 void setProperty(const char* key,const QVariant& value) {values[key]=value;}
 QVariant getProperty(const char*) {return QVariantMap{};}
};
struct PlayerComponent {Mpv* m_mpv; void updateVideoAspectSettings();};
'''+method+r'''
int main() {
 Mpv mpv; PlayerComponent player{&mpv};
 chosen="normal"; player.updateVideoAspectSettings();
 assert(mpv.values["video-aspect-override"].toString()=="-1");
 chosen="force_4_3"; player.updateVideoAspectSettings();
 assert(mpv.values["video-aspect-override"].toString()=="4:3");
 chosen="force_16_9"; player.updateVideoAspectSettings();
 assert(mpv.values["video-aspect-override"].toString()=="16:9");
 chosen="custom"; player.updateVideoAspectSettings();
 assert(mpv.values["video-aspect-override"].toString()=="16:9");
 puts("aspect normal container / forced ratios / custom untouched PASS");
}
'''
work=Path('/src/aspect-contract');work.mkdir(exist_ok=True)
(work/'contract.cpp').write_text(harness)
flags=subprocess.check_output(['pkg-config','--cflags','--libs','Qt6Core'],text=True).split()
subprocess.run(['g++','-std=c++17','-fPIC',str(work/'contract.cpp'),*flags,'-o',str(work/'contract')],check=True)
subprocess.run([str(work/'contract')],check=True)
