"""build_win.py — 打包成 Windows 桌面软件（PyInstaller）

    python build_win.py                 # 目录版（推荐：启动快，便于排障）
    python build_win.py --onefile       # 单文件 exe（拷一个文件就走，启动稍慢）
    python build_win.py --console       # 保留控制台窗口（排查启动失败时用）

产物：dist/培训教学质量评估系统/培训教学质量评估系统.exe

依赖：pip install pyinstaller。本项目运行期零第三方依赖，打包工具是唯一需要装的东西；
离线机器装不上时，用根目录的「启动桌面版.vbs」直接跑源码，功能完全一致。
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = '培训教学质量评估系统'
ICON = os.path.join(HERE, 'assets', 'app.ico')
ENTRY = os.path.join(HERE, 'desktop', 'main.py')

# 数据文件：静态资源与 SQL 种子必须按源码里的相对位置随包带走
ADD_DATA = [
    ('frontend', 'frontend'),
    (os.path.join('backend', 'schema.sql'), 'backend'),
    (os.path.join('backend', 'seed'), 'backend/seed'),
]

HIDDEN = [
    'modules.m1_courses', 'modules.m2_media', 'modules.m3_governance',
    'modules.m4_gateway', 'modules.m5_indicators', 'modules.m6_fusion',
    'modules.m7_report', 'modules.m8_import', 'modules.m9_desktop', 'modules.system',
    'core.probes', 'core.gates', 'core.pipeline', 'core.providers',
    'core.docx', 'core.membership', 'core.tasks', 'core.native_win',
    'scan_dir', 'seed.demo',
]

EXCLUDE = ['tkinter', 'unittest', 'pydoc_data', 'test', 'distutils', 'setuptools']


def check_env():
    missing = []
    try:
        import PyInstaller  # noqa: F401
    except Exception:
        missing.append('pyinstaller')
    for path in (ICON, ENTRY, os.path.join(HERE, 'frontend', 'index.html')):
        if not os.path.exists(path):
            missing.append(path + '（缺失）')
    return missing


def build(onefile=False, console=False):
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
           '--name', NAME, '--distpath', os.path.join(HERE, 'dist'),
           '--workpath', os.path.join(HERE, 'build_pyi'),
           '--specpath', os.path.join(HERE, 'build_pyi'),
           '--icon', ICON]
    cmd.append('--onefile' if onefile else '--onedir')
    cmd.append('--console' if console else '--windowed')
    for src, dst in ADD_DATA:
        cmd += ['--add-data', '%s%s%s' % (os.path.join(HERE, src), os.pathsep, dst)]
    for m in HIDDEN:
        cmd += ['--hidden-import', m]
    for m in EXCLUDE:
        cmd += ['--exclude-module', m]
    cmd.append(ENTRY)

    print('执行：')
    print('  ' + ' '.join('"%s"' % c if ' ' in c else c for c in cmd))
    print()
    rc = subprocess.call(cmd, cwd=HERE)
    if rc != 0:
        print('\n打包失败，退出码 %d' % rc)
        return rc

    out = os.path.join(HERE, 'dist', NAME + ('.exe' if onefile else ''))
    print('\n完成：%s' % out)
    print('\n首次运行会在 %%LOCALAPPDATA%%\\EvalConsole\\data 建库；'
          '若希望「拷走即用」，在 exe 同目录建一个空的 data 文件夹，'
          '程序会自动改用它（便携模式）。')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='打包 Windows 桌面版')
    ap.add_argument('--onefile', action='store_true', help='打成单个 exe')
    ap.add_argument('--console', action='store_true', help='保留控制台（排障）')
    args = ap.parse_args(argv)

    missing = check_env()
    if missing:
        print('缺少打包条件：')
        for m in missing:
            print('  - ' + m)
        if 'pyinstaller' in missing:
            print('\n请先安装：pip install pyinstaller')
            print('离线机器装不上时，直接用「启动桌面版.vbs」运行源码，功能完全一致。')
        return 2

    # 图标没生成就先补一个，免得打包出来是默认图标
    if not os.path.exists(ICON):
        try:
            import build_icon
            build_icon.main()
        except Exception as exc:
            print('图标生成失败（不影响打包）：%s' % exc)

    for stale in ('build_pyi', 'dist'):
        p = os.path.join(HERE, stale)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)

    return build(args.onefile, args.console)


if __name__ == '__main__':
    sys.exit(main())
