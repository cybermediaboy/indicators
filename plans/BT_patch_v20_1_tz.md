# ТЗ: Патч BT-Loop v20 — Устранение структурных дефектов чанкового валидатора

**Проект:** Combined Vector Bands v20 setupsDB  
**Файл:** `Combined Vector Bands v20 setupsDB.pine`  
**Приоритет:** HIGH — дефекты влияют на корректность BT-результатов и прогресс валидации  
**Версия патча:** 20.1

---

## 1. Контекст и область изменений

BT-цикл (`bt_phase == 1`) выполняет ретроактивную валидацию исторических сетапов через
цепочку: **SetupsLib.f_simulate_bt_position → kNN-поиск → MC-симуляция → mc_confirmed**.
Найдено 5 структурных дефектов в одном loop-блоке. Все правки локальны — не затрагивают
SetupsLib, kNNLib, MCLib и глобальные UDT.

---

## 2. Дефекты и патчи

### Bug BT-01 — Двойной inner-loop в `use_setup_direction`-ветке (критический)

**Описание:**  
В ветке `if use_setup_direction` внутри `for run = 0 to bt_mc_runs - 1` присутствует
повторный цикл `for h = 0 to mc_hz - 1` — идентичный тому, что уже отработал снаружи
этого блока для вычисления `priceA` / `priceB`. Результат: `priceA` / `priceB` обновляются
**дважды** за один MC-run, проходя горизонт дважды. `pathHighA/B`, `pathLowA/B` строятся
на дважды смещённых ценах. `is_win_A/B` и `is_loss_A/B` — заведомо некорректны.

**Симптомы:**  
- `mc_pct_agree` систематически завышен в режиме "Setup Direction"  
- `mc_confirmed` даёт ложные подтверждения на сетапах с малым TP%

**Патч:**  
Удалить внутренний дублирующий `for h = 0 to mc_hz - 1` внутри `if use_setup_direction`.  
Заменить его трекингом пути (`pathHigh/pathLow`) через **отдельный проход по уже
сгенерированным `priceA/priceB`** — используя `array` накопленных промежуточных цен,
либо пересчитывая только high/low из финального `priceA/priceB` с консервативным допущением
(see Patch BT-01 в разделе 4).

**Риск:** Изменит значения `mc_pct_agree` / `mc_confirmed` для всех исторических сетапов
в режиме "Setup Direction". Это **ожидаемо и желаемо** — текущие значения некорректны.

---

### Bug BT-02 — `pathHigh/pathLow` инициализируются от конечной цены, не от `entry_price` (критический)

**Описание:**  
```pine
float pathHighA = priceA   // priceA уже — финал inner-loop, не начало пути
float pathLowA  = priceA
```
Трекинг high/low пути начинается не с точки входа, а с конечной точки симуляции.
Если цена шла вверх и упала ниже start — `pathLowA` никогда не захватит минимум пути,
`is_loss_A` будет `false` при реальном стоп-ауте.

**Патч:**  
Инициализировать `pathHighA/B` и `pathLowA/B` от `rec.entry_price`:
```pine
float pathHighA = rec.entry_price
float pathLowA  = rec.entry_price
float pathHighB = rec.entry_price
float pathLowB  = rec.entry_price
```
Накопление high/low выполнять на каждом шаге `h` внутри одного (не дублированного) цикла.

---

### Bug BT-03 — `fb` в inner-loop использует `offset` вместо `chosen_idx` (средний)

**Описание:**  
```pine
int fb = offset + h + 1  // FIX: use offset (array index) not rec.bar_idx
```
Комментарий говорит "use offset", но `offset` — это индекс самого сетапа в `arr_close`,
а MC-путь должен проигрываться **от `chosen_idx`** (аналог-бар из kNN).
Использование `offset` означает, что MC всегда симулирует будущее именно с бара сетапа,
игнорируя kNN-аналог. Это нарушает смысл kNN-валидации: сравниваем не с аналогом, а с собой.

**Патч:**  
```pine
int fb = chosen_idx + h + 1
```
Проверить, что guard `if fb >= csize_bt` сохраняется.

---

### Bug BT-04 — `valid_this_chunk` инкрементируется до проверки `offset` (малый, смещение метрик)

**Описание:**  
```pine
valid_this_chunk += 1

int offset = rec.bar_idx - (bar_index - csize_bt + 1)
if offset < 0 or offset >= csize_bt
    continue  // Skip is FREE
```
Счётчик `valid_this_chunk` увеличивается **до** проверки валидности `offset`. Сетапы с
невалидным `offset` (например, слишком старые — вышли за буфер `arr_close`) считаются
как использованные из `heavy_budget` де-факто, хотя строка `continue` помечена "Skip is FREE".  
Фактически `heavy_budget` при этом **не** декрементируется — это правильно. Но
`valid_this_chunk` растёт на "мусорных" записях, искажая логику прогресса если она
опирается на этот счётчик.

**Патч:**  
Переместить `valid_this_chunk += 1` после проверки `offset`:
```pine
int offset = rec.bar_idx - (bar_index - csize_bt + 1)
if offset < 0 or offset >= csize_bt
    continue

valid_this_chunk += 1  // только валидные
```

---

### Bug BT-05 — `array.set(bt_setups, s - 1, rec)` после forward-bias: `s` уже инкрементирован (малый, потенциальный off-by-one)

**Описание:**  
Комментарий в коде: `// s already incremented at line 2458`.  
Это означает, что `array.set(bt_setups, s - 1, rec)` — верно **только если** `s` был
инкрементирован ровно один раз перед этим `continue`. Если в будущем добавится ещё один
`s += 1` до блока forward-bias check (рефакторинг, новый фильтр) — индекс сдвинется.

**Патч:**  
Ввести локальную переменную `int cur_s = s - 1` сразу после `s += 1` и использовать
`cur_s` во всех последующих `array.set(bt_setups, ...)` внутри этой итерации:
```pine
s += 1
int cur_s = s - 1  // зафиксированный индекс текущей записи

// далее везде:
array.set(bt_setups, cur_s, rec)
```

---

## 3. Таблица дефектов

| ID | Серьёзность | Компонент | Влияние на результат |
|----|-------------|-----------|----------------------|
| BT-01 | Критический | MC inner-loop дублирование | mc_pct_agree некорректен в Setup Direction режиме |
| BT-02 | Критический | pathHigh/pathLow инициализация | is_win / is_loss ложные |
| BT-03 | Средний | fb = offset вместо chosen_idx | MC не использует kNN-аналог, симулирует с бара сетапа |
| BT-04 | Малый | valid_this_chunk порядок | Счётчик прогресса искажён на невалидных offset |
| BT-05 | Малый | array.set off-by-one риск | Хрупкость к рефакторингу |

---

## 3.1. Таблица критериев фильтрации колонок BT Summary

| Колонка | Критерии включения | Переменные | Семантика |
|---------|-------------------|-----------|-----------|
| **All Setups** | `actual_pnl != na` (трейд закрыт по OHLC) | `bt_all_*` | Все fired setups без validation фильтров. BT симуляция запускается **до** проверок `hist_avail`, kNN, forward bias. Показывает "как бы сработали все сетапы по реальным OHLC". |
| **Validated** | `actual_pnl != na` **AND** `hist_avail >= bt_min_history` **AND** kNN candidates > 0 **AND** no forward bias | `bt_raw_*` | Setups прошедшие полную validation цепочку: достаточно истории для kNN, найдены аналоги, нет утечки будущего. |
| **MC Conf** | Validated **AND** `mc_confirmed == true` | `bt_filt_*` | Подмножество Validated, где MC oracle согласился с направлением сетапа (`mc_pct_agree >= bt_agree_pct`). |

**Ключевое отличие:**  
- **All Setups** = детерминированная ретроспективная симуляция на OHLC для **всех** сетапов из `bt_setups`  
- **Validated** = та же симуляция, но только для сетапов прошедших validation (kNN, history, bias checks)  
- **MC Conf** = Validated + стохастическая MC-фильтрация по `mc_pct_agree`

---

## 4. Patch BT-01: детальный план замены inner-loop

**Текущий (некорректный) flow:**

```
outer: for run = 0 to bt_mc_runs - 1
    // Шаг 1: генерация пути (цикл A)
    for h = 0 to mc_hz - 1
        priceA *= exp(hr + z*ns)   // путь от chosen_idx
        priceB *= exp(hr - z*ns)

    if use_setup_direction:
        // Шаг 2: ДУБЛИРУЮЩИЙ цикл B — повторно двигает priceA/B
        for h = 0 to mc_hz - 1    // <-- УДАЛИТЬ
            ...
            pathHighA = max(pathHighA, priceA)
```

**Корректный flow (после патча):**

```
outer: for run = 0 to bt_mc_runs - 1
    float pathHighA = rec.entry_price
    float pathLowA  = rec.entry_price
    float pathHighB = rec.entry_price
    float pathLowB  = rec.entry_price

    // Единственный цикл — генерация + трекинг одновременно
    for h = 0 to mc_hz - 1
        int fb = chosen_idx + h + 1        // Bug BT-03 fix
        if fb >= csize_bt
            break
        float cur  = array.get(arr_close, fb)
        float prev = array.get(arr_close, fb - 1)
        float hr   = (not na(cur) and not na(prev) and prev > 0) ? math.log(cur / prev) : 0.0
        float u1   = math.max(1e-10, MCLib.f_prng(rec.bar_idx + run * 997 + h * 61, 11))
        float u2   = MCLib.f_prng(rec.bar_idx + run * 991 + h * 67, 17)
        float z    = math.sqrt(-2.0 * math.log(u1)) * math.cos(6.2831853 * u2)
        priceA    *= math.exp(hr + z * ns)
        priceB    *= math.exp(hr - z * ns)
        pathHighA  := math.max(pathHighA, priceA)
        pathLowA   := math.min(pathLowA,  priceA)
        pathHighB  := math.max(pathHighB, priceB)
        pathLowB   := math.min(pathLowB,  priceB)

    // Только для use_setup_direction — проверка TP/SL по трекингу пути
    if use_setup_direction
        float target_px = rec.entry_price * (1.0 + (rec.tp_pct / 100.0) * (is_long ? 1.0 : -1.0))
        float stop_px   = rec.entry_price * (1.0 - (math.abs(rec.sl_pct) / 100.0) * (is_long ? 1.0 : -1.0))
        bool is_win_A  = is_long ? (pathHighA >= target_px) : (pathLowA  <= target_px)
        bool is_loss_A = is_long ? (pathLowA  <= stop_px)   : (pathHighA >= stop_px)
        bool is_win_B  = is_long ? (pathHighB >= target_px) : (pathLowB  <= target_px)
        bool is_loss_B = is_long ? (pathLowB  <= stop_px)   : (pathHighB >= stop_px)
        paths_agree += (is_win_A and not is_loss_A) ? 1 : 0
        paths_agree += (is_win_B and not is_loss_B) ? 1 : 0
        dir_agree   += is_long ? (priceA > rec.entry_price ? 1 : 0) : (priceA < rec.entry_price ? 1 : 0)
        dir_agree   += is_long ? (priceB > rec.entry_price ? 1 : 0) : (priceB < rec.entry_price ? 1 : 0)
    else
        // Best MC Direction — без изменений
        int long_agree  = (priceA > rec.entry_price ? 1 : 0) + (priceB > rec.entry_price ? 1 : 0)
        int short_agree = (priceA < rec.entry_price ? 1 : 0) + (priceB < rec.entry_price ? 1 : 0)
        paths_agree += (math.max(long_agree, short_agree) >= 2) ? 2 : math.max(long_agree, short_agree)
        dir_agree   += math.max(long_agree, short_agree)
    total_paths += 2
```

**Что убрать:**  
Весь блок `for h = 0 to mc_hz - 1` внутри `if use_setup_direction` (примерно 25 строк
с `float pathHighA = priceA` ... `pathLowB := math.min(...)`).

---

## 5. Порядок применения патчей

1. **BT-05** — добавить `cur_s` (нулевой риск, 1 строка)  
2. **BT-04** — переместить `valid_this_chunk += 1` (нулевой риск, 2 строки)  
3. **BT-02** — изменить инициализацию `pathHigh/pathLow` (малый риск)  
4. **BT-03** — заменить `offset` → `chosen_idx` в `fb` (средний риск, проверить guard)  
5. **BT-01** — удалить дублирующий inner-loop, объединить с основным (высокий риск, требует регрессионный тест)

---

## 6. Тестирование после патча

| Тест | Метод | Критерий прохождения |
|------|-------|----------------------|
| Регрессия mc_pct_agree | Сравнить таблицу BT до/после на 50+ сетапах | Значения изменились (ожидаемо), нет NaN, нет 100% agree |
| Forward bias guard | Проверить лог chosenids при offset < mc_horizon | Все forward_bias_detected = true корректно пропускаются |
| Path tracking | Сетап LONG с TP=2%, SL=1% на известном баре | is_win только если путь достиг TP до SL |
| BT Progress | Активный чарт с частыми сетапами | Progress не зависает на "..." при mc_phase != 0/4 |
| Budget accounting | bt_heavy_budget=8, 20 setups | valid_this_chunk <= 8, нет пропуска невалидных в счётчик |

---

## 7. Вне области патча (отдельные задачи)

- **Bug #9** (starvation BT при активном MC) — архитектурная задача, требует отдельного ТЗ.
  Предлагаемый подход: кооперативный yield через `bt_phase` с временным слотом на каждые N
  тиков независимо от `mc_phase`.
- Рефакторинг `f_simulate_bt_position` — вне этого патча, SetupsLib.
- Унификация `f_hierarchical_tournament_backtest_signaware` сигнатуры — kNNLib задача.
