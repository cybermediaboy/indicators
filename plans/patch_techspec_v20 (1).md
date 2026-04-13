# ТЗ на патч архитектуры — CVB System v20 → v21

**Дата:** 2026-04-13  
**Базовая версия:** `Combined Vector Bands v20 setupsDB.pine`  
**Целевые файлы:** `SetupsLib-4`, `setupsDBGem`, `MCLib-2`, `kNNLib-3`, `TaUtilityLib-5`, `paste-6.txt` (индикатор)

---

## 1. Состояние архитектуры: Диагностика

### 1.1 UDT-ландшафт (полная карта)

| UDT | Файл-владелец | Экспортируется | Назначение |
|-----|--------------|---------------|-----------|
| `Family` | SetupsLib | ✅ | Классификация режима рынка |
| `SetupSpec` | SetupsLib | ✅ | Полная спецификация сетапа (SSoT) |
| `SetupConfig` | setupsDBGem | ✅ | Контракт вывода из `evaluate_all` |
| `SetupEvent` | SetupsLib | ✅ | Срабатывание сетапа (ID + confidence + tooltip) |
| `SetupSignal` | SetupsLib | ✅ | Сигнал для внешнего потребления |
| `SetupContext` | SetupsLib | ✅ | Значения 6 осцилляторов (flat-struct) |
| `OscContext` | SetupsLib | ✅ | Значения + перцентили осцилляторов (6-slot arrays) |
| `ValidationState` | SetupsLib | ✅ | Состояние валидатора MAE/MFE |
| `LevelTracker` | SetupsLib | ✅ | Sweep-aware TP/SL линии |
| `MCPhysicsParams` | MCLib | ✅ | Параметры физики MC-симуляции |
| `ActivePosition` | индикатор | ❌ (локально) | Текущая открытая позиция |
| `HistoricalSetup` | индикатор | ❌ (локально) | Запись для бэктеста |
| `ConfluenceCluster` | индикатор | ❌ (локально) | Уровень confluence |

**Вывод:** UDT-граница в целом соблюдена. Проблемы — в деталях (см. ниже).

---

### 1.2 Реестр выявленных нарушений

#### P1 — Критические (нарушают SSoT или вызывают runtime-баги)

**[P1-A] Дублирование логики классификации Family**

`fgetmcfamily` присутствует в **двух файлах** с идентичной логикой:
- `SetupsLib` → `f_get_mc_family(f1..f6)` — 6 features
- `MCLib` → `f_get_mc_family(f1..f6)` — 6 features (дубль)

Индикатор вызывает `MCLib.fgetmcfamily(...)` и `SetupsLib.fclassifymarketstate(...)` — это параллельные пути классификации с разными сигнатурами, которые могут расходиться в пограничных случаях. **SSoT нарушен.**

**[P1-B] `SetupConfig` vs `SetupSpec` — двойная система метаданных сетапов**

`SetupConfig` (setupsDBGem) содержит поля:
`id, name, dir, tppct, slpct, holdbars, wr, sharpe, isactive, edgeratio, thesis, showstoppermask, code, mask, mcfamily, tooltip`

`SetupSpec` (SetupsLib) содержит:
`id, name, dir, family, wr, sharpe, tppct, slpct, avgbars, tooltip, timestop, edgeratio, thesis, thesisflags, showstoppermask, impulsepenaltyscale, code, mask`

Существует адаптер `f_config_to_spec(...)` с 14 параметрами — признак архитектурного шва. Вызов `f_register_event_v2` требует `SetupSpec`, но `evaluate_all` возвращает `SetupConfig`. **Каждый `f_fire_setup_byid` в индикаторе проходит через этот адаптер на каждом баре.**

**[P1-C] `fcheckshowstoppers` vs `fevalshowstoppers` — параллельные имплементации**

В SetupsLib присутствуют две функции с разными сигнатурами для одной задачи:
- `f_check_showstoppers(SetupSpec, SetupContext)` — принимает `SetupContext` (flat-struct)
- `f_eval_showstoppers(int mask, OscContext)` — принимает `OscContext` (arrays)

Обе экспортированы. `f_register_event_v2` использует `OscContext`-версию, тогда как `SetupContext` — фактически устаревший тип. Это создаёт два параллельных пути и путаницу при поддержке.

**[P1-D] Deprecated-код без срока удаления в MCLib**

Три функции в MCLib помечены `DEPRECATED` но не удалены:
- `f_run_lite_antithetic_mc(...)` — 40+ строк
- `f_run_realtime_mc_chunk(...)` — 50+ строк
- `f_update_progressive_percentiles(...)` — 30+ строк

Все три заменены `f_welford_knn_bootstrap` и `f_welford_knn_chunk`. Присутствие создаёт компиляторный балласт и риск случайного использования.

#### P2 — Структурные (нарушают разделение ответственности)

**[P2-A] `fexitlogic` в SetupsLib — нарушение SRP**

`f_exit_logic(...)` — deprecated-функция, которая смешивает:
- логику выхода (расчёт SL/TP/PredFlip)
- формирование текста лейбла
- формирование цвета лейбла
- формирование координаты Y лейбла

Уже есть корректная декомпозиция: `f_evaluate_exit` + `f_exit_label_text` + `f_exit_label_color`. Deprecated-функция должна быть удалена, не просто помечена.

**[P2-B] `f_find_setup_spec` — дублирует `f_get_spec`**

В SetupsLib экспортированы обе функции для поиска в `array[SetupSpec]` по `id`:
- `f_find_setup_spec(...)` — возвращает 8 отдельных значений через tuple
- `f_get_spec(...)` — возвращает `SetupSpec` напрямую

`f_find_setup_spec` — legacy-API. SSoT нарушен: два пути для одного действия.

**[P2-C] `SetupContext` — устаревший flat-struct параллельно `OscContext`**

`SetupContext` содержит 20 float-полей, дублирующих содержимое `OscContext` в другом формате. `OscContext` — актуальный тип (6-slot arrays + percentiles). `SetupContext` используется только в `f_check_showstoppers` (deprecated-путь) и больше нигде в активном коде.

**[P2-D] `ActivePosition` и `HistoricalSetup` определены локально в индикаторе**

Оба UDT нужны только индикатору, но `ActivePosition` содержит поля связанные с exit-логикой SetupsLib (`exitcode`, `levelsidx`, `levelscnt`), а `HistoricalSetup` — с kNN-движком (`f1snap..f7snap`, `packedsnap`, `familysnap`). Граница неоднозначна.

**[P2-E] `fgetmcfamily` в MCLib — нарушение зон ответственности**

MCLib должен содержать только: PRNG, Welford MC bootstrap, cone drawing, backtest table render. Классификация Family — ответственность SetupsLib/кластер-логики. Дублирование в MCLib нарушает эту границу.

#### P3 — Косметические / технический долг

**[P3-A] `kNNLib` содержит legacy 6-feature API параллельно 7-feature**

Экспортированы обе версии:
- `f_find_knearest(f1..f6, ...)` — 6 features
- `f_find_knearest7(f1..f7, ...)` — 7 features (актуально)
- `f_calculate_confidence(f1..f6, ...)` — 6 features
- `f_calculate_confidence7(f1..f7, ...)` — 7 features
- `f_euclidean_distance(f1..f6, ...)` — 6 features (нигде не вызывается напрямую)
- `f_median_distance(...)` — 6 features (нигде не вызывается активно)

`f_knn_scan` и `f_knn_select` — compatibility wrappers v19, не используются в v20.

**[P3-B] `f_build_family_table` вызывается на каждом баре через `var families = ...`**

Технически корректно (var), но функция аллоцирует array[5] каждый раз при вызове без `var`. Нужна документация что `var` обязателен.

**[P3-C] `thesisflags` в `SetupSpec` vs string `thesis` в `SetupConfig`**

`SetupSpec.thesisflags` — int-битовое поле.  
`SetupConfig.thesis` — string ("MR", "BURST", "MOMENTUM" и т.д.).  
Адаптер `f_config_to_spec` передаёт `thesisflags=0` жёстко. Логика `f_register_event_v2` использует `thesisflags` для penalty-расчёта. **Penalty всегда 0 для setups из setupsDBGem.**

**[P3-D] `f_simulate_bt_position` принимает `arrayfloat arrpredma` но индикатор передаёт глобальный массив**

Нет документации ограничений на размер и offset-гарантии. Баг #10 помечен как resolved, но комментарий "NOTE" остаётся без теста.

---

## 2. Патч: Задачи (приоритет → зависимости)

### ЗАДАЧА 1: Удалить `fgetmcfamily` из MCLib, сделать SSoT в SetupsLib

**Файлы:** `MCLib-2.pine`  
**Зависит от:** ничего  
**Риск:** низкий — нужно проверить все вызовы MCLib.fgetmcfamily в индикаторе

**Действия:**
1. Удалить `f_get_mc_family(f1..f6)` из MCLib полностью.
2. В индикаторе заменить все `MCLib.fgetmcfamily(...)` на `SetupsLib.fgetmcfamily(...)`.
3. Убедиться что `SetupsLib.fgetmcfamily` и `SetupsLib.fclassifymarketstate` не пересекаются по use-case и задокументировать разницу: `fgetmcfamily` = 6-feature pure classifier, `fclassifymarketstate` = physics-based с position/velocity/coupling.

**Критерий завершения:** в MCLib нет ни одной функции с "family" в названии.

---

### ЗАДАЧА 2: Удалить три DEPRECATED-функции из MCLib

**Файлы:** `MCLib-2.pine`  
**Зависит от:** ничего  
**Риск:** нулевой — все три уже не вызываются в v20

**Действия:**
1. Удалить `f_run_lite_antithetic_mc(...)`.
2. Удалить `f_run_realtime_mc_chunk(...)`.
3. Удалить `f_update_progressive_percentiles(...)`.
4. Удалить устаревший комментарий "DEPRECATED Legacy pool-based MC helper".

**Критерий завершения:** MCLib содержит только: `f_prng`, `MCPhysicsParams`, `f_eval_validator_path`, `f_calc_validator_rr`, `f_welford_knn_bootstrap`, `f_welford_knn_chunk`, `f_draw_mc_cones`, `f_render_backtest_table`.

---

### ЗАДАЧА 3: Устранить дублирование `SetupConfig` / `SetupSpec` через расширение SetupConfig

**Файлы:** `setupsDBGem.pine`, `SetupsLib-4.pine`, индикатор  
**Зависит от:** Задача 1  
**Риск:** средний — изменение UDT-контракта

**Контекст:** Адаптер `f_config_to_spec(14 params)` — архитектурный шов. Проблема в том, что `SetupSpec` содержит `impulsepenaltyscale` и `thesisflags` (int), которых нет в `SetupConfig`, а `SetupConfig` содержит `mcfamily` и `isactive`, которых нет в `SetupSpec`.

**Вариант A (рекомендуется): добавить `thesisflags` в `SetupConfig`**

```pine
// setupsDBGem.pine — добавить поле в UDT
export type SetupConfig
    // ... existing fields ...
    int thesisflags  // 0=none, 1=anti-impulse, 2=coupling-required
    float impulsepenaltyscale  // default 1.0
```

Обновить все `SetupConfig.new(...)` в `evaluate_all` с явными значениями `thesisflags` и `impulsepenaltyscale`.

Обновить `f_config_to_spec` чтобы передавал реальные значения, а не жёстко 0.

**Вариант B (альтернатива): сделать `f_register_event_v2` принимать `SetupConfig` напрямую**

Перегрузить или создать `f_register_event_v3(arraySetupEvent, bool, SetupConfig, OscContext, float, string)` в SetupsLib, который сам строит внутренний `SetupSpec`. Удалить внешний адаптер.

**Действия (Вариант A):**
1. Добавить `thesisflags` (default 0) и `impulsepenaltyscale` (default 1.0) в `SetupConfig`.
2. Заполнить правильные значения `thesisflags` в каждом `SetupConfig.new(...)` в `evaluate_all`:
   - Сетапы с thesis `MR` или `DECOUPLE`: `thesisflags=1` (anti-impulse penalty)
   - Сетапы с thesis `MOMENTUM` или `RECOUPLE`: `thesisflags=2` (coupling check)
3. Обновить `f_config_to_spec` — убрать hardcoded `thesisflags=0`.
4. Добавить `assert`-комментарий в `f_register_event_v2`: "thesisflags must be non-zero for penalty to apply".

**Критерий завершения:** `f_score_confidence` в SetupsLib корректно применяет penalty для setups из setupsDBGem.

---

### ЗАДАЧА 4: Убрать `SetupContext` и `f_check_showstoppers` (flat-struct путь)

**Файлы:** `SetupsLib-4.pine`, индикатор  
**Зависит от:** нет прямых зависимостей, но лучше после Задачи 3  
**Риск:** низкий — `SetupContext` не используется в активном коде v20

**Действия:**
1. Проверить grep по индикатору: нет ли вызовов `f_check_showstoppers(SetupSpec, SetupContext)`.
2. Если нет — пометить `type SetupContext` и `f_check_showstoppers` как `// DEPRECATED: use f_eval_showstoppers(mask, OscContext)`.
3. Добавить TODO-маркер: "Remove in SetupsLib v7".
4. Не удалять пока — библиотека публичная, breaking change требует версии.

**Критерий завершения:** в SetupsLib один путь showstopper-проверки через `OscContext`.

---

### ЗАДАЧА 5: Удалить `f_exit_logic` и `f_find_setup_spec` из SetupsLib

**Файлы:** `SetupsLib-4.pine`, индикатор  
**Зависит от:** ничего  
**Риск:** низкий при условии проверки вызовов

**Действия:**
1. Grep в индикаторе: поиск вызовов `SetupsLib.fexitlogic(...)` и `SetupsLib.ffindsetupspec(...)`.
2. Если есть — заменить:
   - `f_exit_logic(...)` → `f_evaluate_exit(...)` + `f_exit_label_text(...)` + `f_exit_label_color(...)`
   - `f_find_setup_spec(...)` → `f_get_spec(...)`
3. Пометить обе функции `// DEPRECATED: Remove in SetupsLib v7`.

**Критерий завершения:** `f_get_spec` — единственный lookup-путь; `f_evaluate_exit` + helpers — единственный exit-путь.

---

### ЗАДАЧА 6: Убрать legacy 6-feature API из kNNLib

**Файлы:** `kNNLib-3.pine`  
**Зависит от:** ничего  
**Риск:** низкий (6-feature API не вызывается в v20 индикаторе)

**Действия:**
1. Пометить как `// DEPRECATED` или удалить:
   - `f_find_knearest(f1..f6, ...)` — 6-feature версия
   - `f_calculate_confidence(f1..f6, ...)` — 6-feature версия
   - `f_euclidean_distance(f1..f6, ...)` — 6-feature, нигде не вызывается напрямую
   - `f_median_distance(...)` — 6-feature
   - `f_knn_scan(...)` — compatibility wrapper v19
   - `f_knn_select(...)` — compatibility wrapper v19
2. Актуальное API: `f_find_knearest7`, `f_calculate_confidence7`, `f_hierarchical_tournament_live`, `f_hierarchical_tournament_backtest`, `f_hierarchical_tournament_backtest_signaware`, `f_sign_aware_filter`, `f_merge_tier`.

**Критерий завершения:** kNNLib экспортирует только 7-feature pipeline + normalization helpers.

---

### ЗАДАЧА 7: Унифицировать `f_build_osc_context` как единую точку сборки OscContext

**Файлы:** `SetupsLib-4.pine` (уже есть `f_build_osc_context`), индикатор  
**Зависит от:** Задача 4  
**Риск:** низкий

**Контекст:** В SetupsLib уже есть `f_build_osc_context(20 params)`. Проверить что все вызовы в индикаторе используют именно его, а не строят `OscContext.new(...)` вручную.

**Действия:**
1. Grep в индикаторе: `OscContext.new(` — найти все прямые инстанциации.
2. Каждый `OscContext.new(...)` заменить на `SetupsLib.fbuildosccontext(...)`.
3. Обновить подпись `f_build_osc_context` если не хватает параметров.

**Критерий завершения:** `OscContext.new` вызывается только внутри `f_build_osc_context` в SetupsLib.

---

## 3. Матрица зависимостей патча

```
Задача 1 (MCLib Family SSoT)
    └─ не блокирует ничего, но логически предшествует Задаче 3

Задача 2 (MCLib deprecated)
    └─ независима, выполняется первой

Задача 3 (SetupConfig thesisflags)
    └─ зависит от: Задача 1 (SSoT Family)
    └─ разблокирует: корректную работу penalty в f_score_confidence

Задача 4 (SetupContext deprecated)
    └─ независима

Задача 5 (f_exit_logic, f_find_setup_spec deprecated)
    └─ независима

Задача 6 (kNNLib legacy 6-feature)
    └─ независима

Задача 7 (OscContext SSoT)
    └─ зависит от: Задача 4 (чтобы SetupContext не мешал)
```

**Рекомендуемая последовательность выполнения:** 2 → 1 → 6 → 5 → 4 → 3 → 7

---

## 4. Архитектурная карта после патча

```
┌─────────────────────────────────────────────────────────┐
│  ИНДИКАТОР (paste-6.txt)                                │
│  Содержит: ActivePosition, HistoricalSetup,             │
│            ConfluenceCluster (локальные UDT)            │
│  Вызывает: evaluate_all → SetupConfig[]                 │
│            f_build_osc_context → OscContext             │
│            f_register_event_v2 → SetupEvent             │
│            f_welford_knn_chunk → Welford accumulators   │
│            f_evaluate_exit → exitcode, trailsl          │
└────────────────┬──────────────────────────────────────┬─┘
                 │                                      │
    ┌────────────▼──────────┐           ┌───────────────▼────────┐
    │  setupsDBGem          │           │  kNNLib-3              │
    │  SSoT: сетап-матрица  │           │  SSoT: 7-feature kNN   │
    │  SetupConfig (owner)  │           │  f_hierarchical_*      │
    │  evaluate_all(...)    │           │  f_turboquant          │
    │  [thesisflags added]  │           │  f_welford_knn_*       │
    └────────────┬──────────┘           └───────────────┬────────┘
                 │                                      │
    ┌────────────▼──────────────────────────────────────▼────────┐
    │  SetupsLib-4                                               │
    │  SSoT: типы движка + engine-функции                       │
    │  Family, SetupSpec, SetupEvent, OscContext,               │
    │  ValidationState, LevelTracker                            │
    │  f_register_event_v2, f_eval_showstoppers,               │
    │  f_score_confidence, f_evaluate_exit,                     │
    │  f_build_osc_context, f_simulate_bt_position,            │
    │  f_classify_market_state, f_get_mc_family (SSoT)         │
    └───────────────────────────────┬────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
    ┌─────────▼──────┐   ┌──────────▼──────┐   ┌──────────▼─────────┐
    │  MCLib-2       │   │  TaUtilityLib-5 │   │  CausalityLib      │
    │  PRNG          │   │  z-score, math  │   │  TE calculation    │
    │  Welford MC    │   │  basis modes    │   │  f_compute_te_*    │
    │  Cone drawing  │   │  f_tanh, etc    │   └────────────────────┘
    │  BT table      │   └─────────────────┘
    └────────────────┘
```

---

## 5. Ревью исходного ТЗ (patch techspec v1)

### Что было верно:

- Задача 1 (аудит регистраторов) — релевантна, `f_register_event` и `f_register_event_auto` в v20 отсутствуют, единственный путь `f_register_event_v2` — верно.
- Задача 2 (удаление регистраторов) — отпала, уже выполнено в v20.
- Задача 3 (мост SetupConfig→SetupSpec) — верно идентифицирована проблема. **Уточнение:** рекомендуется Вариант A (добавить `thesisflags` в `SetupConfig`), а не `f_register_event_v3`, поскольку это требует меньше изменений в SetupsLib.
- Задача 5 (deprecated-маркер на SetupsLibQuen) — не применимо к данному кодобазу (нет SetupsLibQuen).

### Что добавляет этот ТЗ (новое):

| № | Проблема | Статус в старом ТЗ |
|---|---------|-------------------|
| P1-A | `f_get_mc_family` дублируется в MCLib | ❌ не было |
| P1-C | `f_check_showstoppers` vs `f_eval_showstoppers` | ❌ не было |
| P2-B | `f_find_setup_spec` дублирует `f_get_spec` | ❌ не было |
| P2-C | `SetupContext` устарел параллельно `OscContext` | ❌ не было |
| P3-A | kNNLib legacy 6-feature API | ❌ не было |
| P3-C | `thesisflags=0` hardcoded в адаптере | частично упомянуто |
| T7 | OscContext SSoT (единая точка сборки) | ❌ не было |

### Приоритизация по impact/risk:

| Задача | Impact | Risk | Строк изменений |
|--------|--------|------|----------------|
| 2 (MCLib deprecated) | medium | нулевой | ~130 удалить |
| 1 (MCLib Family) | high | низкий | ~15 удалить + 3 в индикаторе |
| 6 (kNNLib legacy) | medium | низкий | ~120 удалить/пометить |
| 5 (exit/find legacy) | low | низкий | пометить 2 функции |
| 4 (SetupContext) | low | низкий | пометить тип + функцию |
| 3 (thesisflags) | **high** | средний | ~30 изменить в setupsDBGem |
| 7 (OscContext SSoT) | medium | низкий | grep + замена в индикаторе |

---

## 6. Инварианты, которые нельзя нарушать

1. **Все массивы — глобальный скоуп.** Никаких `array.new*` внутри функций без передачи как параметра или возврата.
2. **`OscContext.new(...)` — только внутри `f_build_osc_context`.** После Задачи 7.
3. **`f_register_event_v2` — единственный путь регистрации события.** Никаких прямых `array.push(events, SetupEvent.new(...))` в индикаторе.
4. **`evaluate_all` — единственная точка условий входа.** Индикатор не дублирует логику условий из setupsDBGem.
5. **MCLib не должен знать о Family/SetupSpec.** После Задачи 1.
6. **kNNLib — domain-agnostic.** Не хранит `setupid`, `family` как семантику — только как `categoryA`/`categoryB` integer labels.

