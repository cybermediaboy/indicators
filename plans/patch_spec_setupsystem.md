# ТЗ на патч: SetupsLib + setupsDBGem + CVB v20

**Проект:** Combined Vector Bands v20 setupsDB  
**Дата:** 2026-04-12  
**Репозиторий:** cybermediaboy/indicators  
**Затронутые файлы:** `libs/SetupsLib.pine`, `libs/setupsDBGem.pine`, `Combined Vector Bands v20 setupsDB.pine`

---

## 1. Контекст и причина патча

Текущая система содержит три точки деградации, которые снижают сигнальное качество, создают дублирование кода и вносят архитектурный разрыв между `SetupConfig` (setupsDBGem) и `SetupSpec` (SetupsLib):

1. **Два устаревших регистратора** (`f_register_event`, `f_register_event_auto`) с hardcoded confidence=0.5 и отключёнными showstoppers/penalties — живут рядом с полным `f_register_event_v2`, создавая риск случайного использования деградированного пути.
2. **Двойная типология сетапов:** `SetupSpec` в SetupsLib и `SetupConfig` в setupsDBGem — два отдельных UDT с частично пересекающимися полями. `evaluate_all()` возвращает `array<SetupConfig>`, но downstream-код в v20 использует `SetupSpec`-совместимые функции SetupsLib, что требует мануального mapping-а.
3. **SetupsLibQuen.pine** (47 KB) остаётся в репо и потенциально импортируется по ошибке. Явного маркера устаревания нет.

---

## 2. Задачи патча

### 2.1 Удаление устаревших регистраторов из SetupsLib

**Что убрать:**
```pine
// УДАЛИТЬ: f_register_event
export f_register_event(array<SetupEvent> engine_events, bool fire_condition, string setup_id, string setup_tooltip, string setup_size_info) =>

// УДАЛИТЬ: f_register_event_auto
export f_register_event_auto(array<SetupEvent> engine_events, array<SetupSpec> setup_db, bool fire_condition, string setup_id, string setup_size_info) =>
```

**Что оставить (единственный путь регистрации):**
```pine
export f_register_event_v2(array<SetupEvent> events, bool condition, SetupSpec spec, OscContext ctx, float impulse_strength, string size_info) =>
```

**Проверить перед удалением:**  
Выполнить поиск в `Combined Vector Bands v20 setupsDB.pine` по строкам:
- `SetupsLib.f_register_event(`  
- `SetupsLib.f_register_event_auto(`

Если вызовы присутствуют — перед удалением функций их нужно заменить на `f_register_event_v2` с правильным `SetupSpec` или `OscContext`. Если вызовов нет — функции удаляются напрямую.

**Ожидаемый результат:** SetupsLib версия инкрементируется. Единственный путь регистрации — `f_register_event_v2`.

---

### 2.2 Мост SetupConfig → SetupSpec (адаптер в SetupsLib)

Проблема: `setupsDBGem.evaluate_all()` возвращает `array<SetupConfig>`. Для использования функций SetupsLib (`f_register_event_v2`, `f_check_showstoppers`, `f_score_confidence`, `f_find_setup_spec`, etc.) нужен `SetupSpec`.

**Реализация адаптера:**

```pine
// Добавить в SetupsLib.pine (секция HELPER FUNCTIONS)
export f_config_to_spec(SetupsDBGem.SetupConfig cfg) =>
    SetupSpec.new(
        id                    = cfg.id,
        name                  = cfg.name,
        dir                   = cfg.dir,
        family                = na,          // family resolves via mc_family int
        wr                    = cfg.wr,
        sharpe                = cfg.sharpe,
        tp_pct                = cfg.tp_pct,
        sl_pct                = cfg.sl_pct,
        avg_bars              = cfg.hold_bars,
        tooltip               = "",           // не хранится в SetupConfig
        timestop              = cfg.hold_bars,
        edge_ratio            = cfg.edgeratio,
        thesis                = cfg.thesis,
        thesis_flags          = 0,            // вычислить из thesis если нужно
        showstopper_mask      = cfg.showstopper_mask,
        impulse_penalty_scale = 1.0,
        code                  = cfg.code,
        mask                  = cfg.mask
    )
```

**Альтернатива (рекомендуется):** Вместо адаптера — добавить в `SetupConfig` поле `string tooltip` и заполнять его в `evaluate_all()`. Это устраняет необходимость в адаптере и делает `SetupConfig` полным контрактом.

**Что выбрать:**
- Если `SetupSpec` планируется к deprecation — выбрать адаптер как временный мост.
- Если `SetupSpec` остаётся — добавить `tooltip` в `SetupConfig` и обновить все 10 `SetupConfig.new(...)` в `evaluate_all()`.

---

### 2.3 Маркировка SetupsLibQuen как deprecated

В начало файла `libs/SetupsLibQuen.pine` добавить:

```pine
// ⚠️ DEPRECATED: SetupsLibQuen.pine — устаревшая версия SetupsLib.
// Не использовать в новых индикаторах. Актуальная библиотека: SetupsLib.pine
// Дата deprecation: 2026-04-12
// Оставлен для backward compatibility с индикаторами на старых версиях импорта.
```

В `Combined Vector Bands v20 setupsDB.pine` убедиться, что импортируется именно `SetupsLib`, а не `SetupsLibQuen` (строка `import cybermediaboy/SetupsLib/22 as SetupsLib` — корректна).

---

### 2.4 OscContext: унифицированный билдер

В v20 `OscContext` собирается вручную в нескольких местах. Добавить в SetupsLib экспортируемую функцию-билдер:

```pine
export f_build_osc_context(
    float vec_osc, float mr_osc, float te_osc, float corr_osc, float ltf_corr, float pred_slope,
    float vec_p25, float vec_p75,
    float mr_p25, float mr_p75, float mr_p2, float mr_p98,
    float te_p25, float te_p75,
    float corr_p20, float corr_p80,
    float ltf_p20, float ltf_p80,
    float pred_p25, float pred_p75
) =>
    OscContext ctx = OscContext.new(
        array.from(vec_osc, mr_osc, te_osc, corr_osc, ltf_corr, pred_slope),
        array.from(vec_p25, mr_p25, te_p25, corr_p20, ltf_p20, pred_p25),
        array.from(vec_p75, mr_p75, te_p75, corr_p80, ltf_p80, pred_p75),
        array.from(vec_p25, mr_p2,  te_p25, corr_p20, ltf_p20, pred_p25),
        array.from(vec_p75, mr_p98, te_p75, corr_p80, ltf_p80, pred_p75)
    )
    ctx
```

Это заменяет разбросанные `OscContext.new(...)` вызовы в v20 единой точкой сборки.

---

### 2.5 Аудит вызовов в v20: что использует какой регистратор

Перед финальной заменой провести поиск по v20:

| Паттерн поиска | Ожидаемое действие |
|---|---|
| `SetupsLib.f_register_event(` | Заменить на `f_register_event_v2` |
| `SetupsLib.f_register_event_auto(` | Заменить на `f_register_event_v2` |
| `SetupsLib.f_register_event_v2(` | Оставить как есть, проверить `OscContext` |
| `SetupSpec.new(` | Проверить: не нужно ли заменить на `f_config_to_spec()` |
| `SetupsLibQuen` | Удалить или заменить на `SetupsLib` |

---

## 3. Требования к реализации (Pine Script constraints)

- Все функции — экспортируемые (`export`), следовать существующему стилю SetupsLib.
- Никаких вложенных функций внутри функций.
- `OscContext` — глобальный массив, не передавать как mutable через функцию (только `values`, `p25`, `p75` через возврат).
- `f_config_to_spec` не изменяет глобальных переменных — только создаёт и возвращает новый `SetupSpec`.
- Все новые `array.get()` защитить проверкой размера перед обращением.
- Документация каждой новой функции: `@function`, `@param`, `@returns` в стиле существующих.

---

## 4. Приоритет и порядок выполнения

| # | Задача | Риск | Зависимости |
|---|---|---|---|
| 1 | Аудит вызовов f_register_event/f_register_event_auto в v20 | Низкий | — |
| 2 | Удаление устаревших регистраторов из SetupsLib | Низкий (если аудит чист) | Задача 1 |
| 3 | Добавление `tooltip` в `SetupConfig` / адаптер | Средний | — |
| 4 | Добавление `f_build_osc_context` в SetupsLib | Низкий | — |
| 5 | Маркировка SetupsLibQuen deprecated | Нулевой | — |
| 6 | Инкремент версий SetupsLib и setupsDBGem | — | 1-4 |

---

## 5. Критерии приёмки

- [ ] SetupsLib не содержит `f_register_event` и `f_register_event_auto`.
- [ ] Все вызовы в v20 используют только `f_register_event_v2`.
- [ ] `SetupConfig` и `SetupSpec` имеют явный мост (адаптер или общее поле `tooltip`).
- [ ] `OscContext` собирается через `f_build_osc_context` во всех точках v20.
- [ ] SetupsLibQuen помечена как deprecated.
- [ ] Индикатор компилируется без ошибок на Pine Script v6.
- [ ] Debug-таблица v20 отображает корректные значения confidence (не hardcoded 0.5).
