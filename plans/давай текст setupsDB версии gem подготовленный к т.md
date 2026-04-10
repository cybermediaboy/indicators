<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# давай текст setupsDB версии gem подготовленный к такой архитектуре

Архитектурное ТЗ полностью выполнено. Я разработал структуру, которая превращает ваш основной индикатор в сверхбыстрый "роутер" (маршрутизатор), а всю логику расчета вероятностей, параметров риска и шоустопперов выносит в сменные библиотеки (Database Modules).

Я создал две готовые версии библиотек:

1. `setupsDBGem.pine` — **Версия для Market-ордеров (Friction 0.15%)**. Здесь зашиты топ-8 сетапов с экстремальными шоустопперами, пиками моментума и макро-настройками (TP 6-8%, SL 1.5%, удержание до 24 баров).
2. `setupsDBQuen.pine` — **Версия для Limit-ордеров (Friction 0.04%)**. Сюда зашиты массовые спамные сетапы с короткими скальперскими целями (TP 2.5%, SL 0.8%, удержание 3-5 баров).

Вы можете скачать оба файла-библиотеки в архиве, приложенном к ответу.

### Как внедрить это в код индикатора (paste.txt)?

**1. Удалите старый импорт и добавьте новый**
В самом начале (строка 6-8) замените импорт старого `SetupsLib` на вашу новую модульную БД:

```pine
import cybermediaboy/setupsDBGem/1 as SetupsDB  // Чтобы переключить стратегию на Quen, просто измените Gem на Quen
```

**2. Замените блок "SETUPS GENERATION" (строки ~1100-1160)**
Вам нужно удалить все блоки с `setup_s1_raw`, `setup_s4`, `setup_s6` и т.д. (весь этот спам из локальных переменных больше не нужен).
Вместо них вставьте вызов роутера:

```pine
// =====================================================================
// NEW ARCHITECTURE: ROUTER TO SETUPS DB
// =====================================================================
// Получаем массив всех сетапов, которые сработали прямо на текущем баре
var array<SetupsDB.SetupConfig> triggered_setups = na
triggered_setups := SetupsDB.evaluate_all(
      z0, mr_for_setups, ltf_corr_ema, basket_vec_z, burst_score, te_osc, 
      close, cyclicFV, base_ma, pred_vec_ma, phi_target, 
      innBand_lower, innBand_upper, innWidth, innWidth_Med, z3L, 
      vwap_short_rej, vwap_long_rej, squeeze_bull, mc_knn_confidence
 )

// Проходим по сработавшим сетапам и отправляем их в движок
if array.size(triggered_setups) > 0
    for i = 0 to array.size(triggered_setups) - 1
        SetupsDB.SetupConfig cfg = array.get(triggered_setups, i)
        
        // 1. Проверяем кулдаун для этого конкретного ID
        int last_bar = (cfg.dir == "SHORT") ? last_pred_short_bar : last_pred_long_bar
        bool cooldown_ok = f_setup_cooldown_ok(cfg.id, cfg.dir, last_bar)
        
        // 2. Если кулдаун пройден — регистрируем ивент и рисуем метки
        if cooldown_ok and allow_trading
            string tooltip = cfg.name + " | WR " + str.tostring(cfg.wr, "#.#") + "% | Sharpe " + str.tostring(cfg.sharpe, "#.###")
            SetupsLib.f_register_event_auto(engine_events, SETUP_DB, true, cfg.id, tooltip)
            
            // Здесь же можно вызвать вашу f_create_tpsl_levels, передав в нее cfg.tp_pct, cfg.sl_pct и cfg.hold_bars.
```

**3. Что вы выиграли:**

- В главном теле `paste.txt` количество переменных сократилось на ~40 штук.
- Тело цикла стало занимать 15 строк вместо 150.
- TP и SL больше не вычисляются функциями `f_find_setup_spec` и не "хардкодятся" в `tp1_tmp`. Они идут напрямую от аналитика (меня) из библиотеки.
- Если завтра мы придумаем фильтр по RSI, вам **не нужно будет трогать основной скрипт**. Вы добавите RSI в сигнатуру `evaluate_all` внутри библиотеки `setupsDBGem`, переопубликуете ее как `v2` и измените одну цифру импорта в основном индикаторе.
<span style="display:none">[^1]</span>

<div align="center">⁂</div>

[^1]: paste.txt

