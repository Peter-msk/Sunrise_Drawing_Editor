"""Stage13 visual acceptance instrument for the real PySide6 widget tree.

Capture light/dark + width breakpoints at ONE logical Qt DPI scale per process.
This is a stricter repeatable evidence collector, not human/physical-DPI approval.
No PDF/DXF/DWG files are touched and no GitHub Actions are needed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys

def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scale',type=float,choices=(1.0,1.25,1.5,1.75),required=True)
    parser.add_argument('--output',type=Path,default=Path('quality/P0_runtime/UI_STAGE13'))
    parser.add_argument('--height',type=int,default=760)
    args=parser.parse_args(argv)
    os.environ['QT_SCALE_FACTOR']=str(args.scale)
    os.environ.setdefault('QT_QPA_PLATFORM','windows' if os.name=='nt' else 'offscreen')
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QApplication, QPushButton
    from drawing_editor.window import DrawingWindow

    app=QApplication([sys.argv[0]])
    window=DrawingWindow()
    args.output.mkdir(parents=True,exist_ok=True)
    records=[]
    try:
        for width in (760,900,1120,1510):
            window.resize(width,args.height)
            window.show()
            app.processEvents(); app.processEvents()
            for theme in ('light','dark'):
                window.set_theme(theme)
                app.processEvents(); app.processEvents()
                cases=[]
                def check(name, passed, detail):
                    cases.append({'name':name,'passed':bool(passed),'detail':detail})
                def rect_of(widget):
                    point=widget.mapTo(window,QPoint(0,0))
                    return QRect(point,widget.size())
                pane_rect=rect_of(window._layers_panel)
                search_rect=rect_of(window.layer_search_frame)
                icon_rect=rect_of(window.layer_search_icon)
                check('theme-state',window._theme==theme and
                      window.light_button.isChecked()==(theme=='light') and
                      window.dark_button.isChecked()==(theme=='dark'),theme)
                check('responsive-panel-bounds',
                      window._files_panel.width()>120 and
                      window._layers_panel.width()>200 and
                      window.canvas.width()>=190,
                      f'files={window._files_panel.width()}, layers={window._layers_panel.width()}, canvas={window.canvas.width()}')
                check('search-bounds',pane_rect.contains(search_rect),
                      f'search={tuple(search_rect.getRect())} / pane={tuple(pane_rect.getRect())}')
                icon_center=window.layer_search_icon.mapTo(
                    window.layer_search_frame,window.layer_search_icon.rect().center())
                center_gap=abs(icon_center.y()-window.layer_search_frame.rect().center().y())
                check('search-icon-centered',center_gap<=3,f'vertical-offset={center_gap}logical px')
                preview_rect=rect_of(window.canvas.parentWidget())
                controls=(window.page_prev_button,window.page_info,
                          window.page_next_button,window.zoom_out_button,
                          window.zoom_label,window.zoom_in_button,window.fit_button)
                places=[rect_of(c) for c in controls]
                check('all-preview-controls-present',
                      all(c.isVisibleTo(window) and preview_rect.contains(r)
                          for c,r in zip(controls,places)),
                      '7 native page/zoom controls inside preview panel')
                overlapping=[]
                for i,r in enumerate(places):
                    for j in range(i+1,len(places)):
                        if r.intersects(places[j]):
                            overlapping.append((i,j))
                check('preview-buttons-not-overlapping',
                      not overlapping,str(overlapping))
                footer=window.export_button.parentWidget()
                export_buttons=(window.export_button,window.browse_button,
                                window.output_folder,window.resolution_combo,
                                window.transparent_png,window.crop_png)
                outer=window.rect()
                check('export-controls-onscreen',
                      all(c.isVisibleTo(window) and outer.contains(rect_of(c))
                          for c in export_buttons),
                      'output path, type, options, browse, export reachable')
                check('export-button-accessibility',
                      bool(window.export_button.accessibleName()) and
                      bool(window.export_button.toolTip()),
                      window.export_button.accessibleName())
                check('theme-icons',
                      not window.layer_search_icon.pixmap().isNull() and
                      not window.light_button.icon().isNull() and
                      not window.dark_button.icon().isNull(),
                      'search/light/dark pixmaps present')
                label=f'{width}_{theme}_{str(args.scale).replace(".","p")}'
                shot=args.output/f'STAGE13_{label}.png'
                saved=window.grab().save(str(shot),'PNG')
                check('captured-screenshot',saved,shot.name)
                records.append({
                    'window_width_requested':width,'theme':theme,
                    'scale':args.scale,'real_device_dpr':window.devicePixelRatioF(),
                    'passed':all(item['passed'] for item in cases),
                    'checks':cases,'screenshot':shot.name if saved else None,
                })
    finally:
        window.close()
        app.processEvents()
        app.quit()
    report={
        'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'qa':'Stage13 PySide6 actual-widget geometry and rendered screenshot',
        'platform':platform.platform(),
        'virtual_qt_scale_factor':args.scale,
        'pass':all(item['passed'] for item in records),
        'records':records,
        'limitations':['QT_SCALE_FACTOR is not physical Windows monitor DPI',
                       'Image capture is not human visual sign-off',
                       'No 15 real OnMap PDF, 402MiB DXF, Windows onefile/Authenticode in this check'],
    }
    target=args.output/f'STAGE13_UI_{str(args.scale).replace(".","p")}.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(('PASS' if report['pass'] else 'FAIL'),
          'Stage13 light/dark UI geometries; evidence:',target)
    return 0 if report['pass'] else 1

if __name__=='__main__':
    raise SystemExit(main())
