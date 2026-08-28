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

## v2.4 — Усиление HDRI ✅ (сделано 2026-08-28, dist out/v2.4.0/, релиз после подтверждения)

Реализовано:
- **«Невидимый для камеры» HDRI**: галка «Hide from Camera» + цвет (чёрный по умолчанию).
  В дерево вставляются MixRGB 'LM Cam Mix' (Color1=env, Color2=камерный цвет, Fac=Is Camera Ray
  из Light Path 'LM Cam Path'). Ensure-функция идемпотентна: on/off перестраивает связи,
  маркеры чистятся Clear HDRI, Apply переустанавливает микс по текущей галке
- **Prev/next стрелки** ◀ ▶ вокруг имени: циклическое листание папки с МГНОВЕННЫМ применением
  (apply вынесен в `_hdri_apply_image`, используется и кнопкой, и стрелками).
  Неизвестная позиция: next → первый, prev → последний
- Кэш превью — **уже был** с v2.1 (enum-колбэк трогает диск только при смене папки), отмечено
  выполненным без переделки
- Мок-тест 109 проверок; мок-фиделити: линк в Blender заменяет существующую связь на входе

## v2.5 — Sun-хелпер ✅ (сделано 2026-08-28, dist out/v2.5.0/, релиз после подтверждения)

Реализовано:
- **Астрономическое ядро написано с нуля** (решение по лицензии: NOAA-алгоритм public domain,
  GPL-код sun-position НЕ копировался → атрибуция не нужна): Julian day → эклиптическая
  долгота → склонение/RA → GMST → часовой угол → азимут/высота. Восход/закат через ha0 (90.833°)
- **Панель SUN** (суб-панель): sun_object (poll LIGHT), Time 0–24, день/месяц/год, широта/
  долгота, UTC offset, North offset, Distance; read-out Elev/Az/Sunrise/Sunset
- **Пресеты**: Noon (12:00), Golden (закат−1ч), Sunset; полярные day/night → WARNING
- **Анимация дня**: keyframe на Time + `frame_change_post` хендлер с guard
  `bpy.app.is_job_running("RENDER"/"OBJECT_BAKE")`
- Read-only поля паттерном self["key"] + геттеры (SP-паттерн)
- Мок-тест 134 проверки: астрономия Москвой (июнь-полдень ~57°/юг, декабрь низко, ночь <0),
  восход/закат, полярная ночь, apply, пресеты, хендлер
- **Грабля-урок:** в HA-формуле был лишний −180° (солнце «на антиподе», el=−10° в полдень) —
  поймали bound-тесты на реальных координатах ДО релиза; не брать формулы «по памяти» без проверок

## v3.0.0 — Большие фичи ✅ (сделано 2026-08-28, dist out/v3.0.0/, релиз после подтверждения)

Реализовано (все три):
- **Интерактивная расстановка** (`light_manager.place_light`): кнопка CURSOR в ⚙-настройках
  света → модалка; mousemove = raycast через `view3d_utils.region_2d_to_origin_3d/vector_3d` +
  `scene.ray_cast`, свет ставится на hit + normal*0.001; Wheel = power ×1.25, Shift+Wheel = size
  (size/shadow_soft_size/angle по типу); LMB/Enter = FINISHED, RMB/Esc = откат трансформа;
  MIDDLEMOUSE/trackpad = PASS_THROUGH (навигация жива); HUD в header+status bar; UNDO
- **Light/shadow linking кликом** (`light_manager.link_pick`, режимы RECEIVER/BLOCKER):
  кнопки в ⚙ (видны только при `light.light_linking`, т.е. Blender 4.x); LMB = тоггл линка
  объекта под курсором (raycast); коллекция создаётся при первом линке
  (`LM Receiver/Blocker <light>`); снапшот обоих списков в invoke, Esc/RMB = rollback;
  Enter = принять; `link_clear` (RECEIVER/BLOCKER/ALL); guard для Blender 3.x
- **Гобо-проекции**: суб-панель Gobo, папка + enum с превью (как IES), prefs `gobo_folder` +
  load_post сид; Apply на активный SPOT: build-ветка (TexCoord Generated → Mapping 'LM Gobo
  Mapping' → TexImage 'LM Gobo' → Emission → Output) и insert-ветка (MixRGB MULTIPLY 'LM Gobo
  Mix' между старым источником цвета и Emission Color, Color1 = старый источник или запечённый
  цвет); Remove восстанавливает старый источник цвета; rotation (градусы)/scale пишутся в Mapping
  живьём; маркеры сносятся Remove
- **Урок (повторение бага розового мира из v2.3):** в первой версии гобо image не присваивался
  TexImage-ноде — поймал себя ДО тестов и добавил мок-проверку `image assigned to node`
- Мок-тест **172 проверки** (было 136): гобо build/insert/remove/update, linking
  create/toggle/snapshot/restore/clear/guard, placement size-key
- **Регрессия найдена при сборке:** legacy-zip v2.4.1 и v2.5.0 ушли БЕЗ bl_info (в Preferences —
  имя папки). В v3.0.0 legacy собирается скриптом с bl_info-преамбулой (docstring первым);
  при выпуске патчей 2.4.x/2.5.1 желательно перевыпустить
- Модалки place/link_pick НЕ тестируются моком (raycast/UI), живой тест — за пользователем

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
