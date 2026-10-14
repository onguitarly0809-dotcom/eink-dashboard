"""页面渲染器：landscape/ 与 portrait/ 两个变体子包，页面函数同名同职责。

cli/web 按当前变体 import epd_dashboard.renderers.{landscape,portrait}；
跨变体共享的只有各变体包内的 common.py（两版设计体系不同，各自演化）。
"""
