# LAMPOCHKA — Roadmap развития

> Сформирован 2026-08-28 по разбору пяти референсов: Lumio, Pro-Lighting Studio v1.3.1,
> Quick Studio, Light Master Pro v1.0, Sun Position v4.4.0.
> Исходники референсов: `work/ref/` (распаковка — `work/ref/_unpacked/`).

## Кем мы остаёмся

LAMPOCHKA — **панель управления существующим светом сцены** в N-панели + HDRI-браузер.
Без бандл-ассетов, работает на любой сцене, single-file архитектура.
PLS/Quick Studio/LMP — продукты-конструкторы из бандл-ассетов: их модель контента нам не
подходит, но паттерны и точечные фичи — да. Sun Position — чистый источник алгоритмов.

## Сводка по референсам

| Референс | Что это | Главная ценность для нас |
|---|---|---|
| Lumio | light manager + IES/gobo/HDRI | HDRI-браузер (взят, v2.1); IES-паттерн; backlog |
| Pro-Lighting Studio | 164 авторских сетапа из .blend + фоны/полы | метаданные в custom props; JSON-манифест; check_list+recreate |
| Quick Studio | конструктор фотостудии из ассет-ригов | libraries.write + matrix trick (пресеты); реестр светов |
| Light Master Pro | гобо-библиотека (1130 PNG) + интерактивное размещение | модалка расстановки; linking кликом; кэш превью |
| Sun Position | солнце по времени/геолокации (GPL-3.0, official) | астрономическое ядро; Sky/HDRI sync; анимация времени |

## v2.3 — Кельвины + IES ✅ (сделано 2026-08-28, дистрибутив out/v2.3.0/)

Реализовано:
- **Kelvin**: тумблер + слайдер 1500–12000K в ⚙-настройках света; `kelvin_to_rgb()` — Tanner
  Helland + sRGB→linear; исходный цвет в `ob["lm_base_color"]` при включении, восстановление
  при выключении. Object-пропсы `lm_use_temperature`/`lm_temperature` (get/set + update)
- **IES-браузер**: суб-панель IES, папка → enum (превью из `thumbnails/<name>.jpg|png`,
  фолбэк-иконка 'LIGHT'), prefs `ies_folder` + автосид через load_post
- **Apply IES — три ветки**: swap (маркер 'LM IES' → только filepath) / build (чистая цепочка
  IES→Emission→Output) / insert (в существующую Emission-цепочку нода вставляется перед
  Strength). Remove IES сносит TEX_IES-ноды. Полл Point/Spot, дисклеймер «Cycles only» в UI
- Мок-тест 75 проверок

## v2.3.1 — Shift+RMB вращение HDRI ✅ (релиз 2026-08-28)

ФичаSmall, выпущена патчем (пользователь: «для 2.4 маловато»):
- Галка «Rotate: Shift+RMB» в HDRI-панели → кеймап RIGHTMOUSE+SHIFT ('3D View') регистрируется
  в register() (guard от дублей), галка работает через **poll** оператора
- Модалка: горизонталь = Z (0.006 рад/px), Esc во время драга = откат, после — Ctrl+Z (флаг UNDO);
  PASS_THROUGH остальным событиям; `INBETWEEN_MOUSEMOVE` обрабатывается
- Статус: хедер вьюпорта + статус-бар, курсор MOVE_X
- **Ключевые уроки**: `modal_handler_add(self)` в invoke ОБЯЗАТЕЛЕН (без него события не
  доставляются, курсор висит); иконки сверять с enum Blender 5.x ('ROTATE' не существует →
  'GESTURE_ROTATE'); мок-тест 97 проверок

## v2.4 — Усиление HDRI (в работе)

- **«Невидимый для камеры» HDRI** — Light Path `Is Camera Ray` → микс с плоским цветом:
  светим HDRI, рендерим на чёрном/заливке (PLS `backgrounds:178-196`)
- Prev/next стрелки листания HDRI (PLS `ui:152-185`)
- Кэш превью (LMP-паттерн) для HDRI-браузера
- Опционально: отдельный world для камеры/отражений (QS `properties.py:254-354`) — тяжёлая, решаем

## v2.5 — Солнце (из Sun Position) — кандидаты

- **Sun-хелпер**: время/дата/широта-долгота → поворот sun light. Ядро `get_sun_coordinates`
  (`sun_calc.py:234-326`, NOAA, чистая математика ~150 строк) — при переносе вынести
  `use_refraction`/`north_offset` в аргументы; **GPL-3.0: копирование кода легально при
  нашей GPL-3.0 + атрибуция (Michael Martin, Damien Picard); сам NOAA-алгоритм — public domain**
- Восход/закат в read-only полях (паттерн вычисляемых геттеров `self["..."]`)
- Пресеты-кнопки «Полдень / Золотой час / Закат» (проще, чем preset-система)
- **Анимация дня**: keyframe на float-свойстве «время» + `frame_change_post` handler
  (`__init__.py:61-73`) + guard рендера `bpy.app.is_job_running("RENDER")`
- Sky Texture sync: Nishita через `isclose`-проверку + сброс mapping.rotation (`sun_calc.py:103-121`);
  HDRI-bind через относительное вращение (`sun_calc.py:27-53`)

## v3 — Большие фичи (выбрать по надобности)

- **Интерактивная расстановка света** (LMP `__init__.py:2502-3204`, облегчённая версия):
  raycast-размещение, колесо = power/size/distance, freeze по Enter, HUD, PASS_THROUGH
  для навигации; УРЕЗАННАЯ — без их нормаль-блендинга и roll
- **Light/shadow linking кликом** по объекту под курсором (LMP `732-829`) со snapshot/rollback —
  удобнее хоткея Lumio; поверх нативного light linking 4.x
- **Гобо-проекции** (подтверждено двумя рефами: Lumio пресеты + LMP 1130 текстур):
  строим проекционную цепочку кодом (не их .blend-группы); ассеты не бандлим — папка пользователя
- Контроллер-empty + Damped Track + Shrinkwrap-snap (LMP `2203-2234`) как аим-паттерн

## Паттерны для внутреннего использования (из рефов)

| Паттерн | Источник | Зачем нам |
|---|---|---|
| Метаданные в custom props объекта | PLS lighting:804-844 | база для Kelvin |
| check_list + recreate для нод | PLS backgrounds:67-111 | надёжный Apply/Clear HDRI |
| JSON-манифест вместо хардкода | PLS setups.json | будущие пресеты |
| Кэш items + «тупой» enum-колбэк | LMP 2092-2145 | быстрые превью-браузеры |
| libraries.write + matrix trick | QS operators:676-745 | сохранение сетапов |
| Вычисляемые props через self["key"] | SP properties:205-240 | read-only поля без рекурсии |
| isclose перед записью в ноду | SP sun_calc:111-114 | Sky/HDRI sync без лишних пересчётов |
| Guard рендера в хендлере | SP __init__:69 | анимация света |
| Настраиваемый хоткей в prefs + poll вкладки | LMP 1276-1321, 1344-1358 | модалки |
| Массовое переприсваивание драйверов при дубликате | LMP 125-142 | если появятся драйверы |
| Деградация без иконок | PLS props:94-182 | robust-браузеры |
| guard-флаг против рекурсии колбеков | PLS conf:43-51 | вместо self-remove хендлеров |

## Не берём (решено)

- Бандл-ассеты и .blend-библиотеки контента (PLS/QS/LMP) — чужая модель поставки
- Магические индексы сокетов и label-конвенции как единственный API (LMP inputs[22], QS по именам)
- Хендлеры-самоудалители, ops внутри update-колбеков (QS handler.py)
- Запись файлов в каталог аддона (все три коммерческих) — только user-ресурсы
- Тяжёлая логика в draw() (PLS warnings каждый редрав)
- PaintMask, EEVEE shadow-plane воркараунд (LMP), аналлеммы/GPU-оверлеи (SP),
  градиентные светильники, композитор, HDRI-выпечка, меш-софтбоксы на драйверах
