from __future__ import annotations
from collections import defaultdict
from datetime import datetime, time as dt_time
from statistics import mean
from app.engines import time_utils
from app.engines.time_utils import (
    to_ny, session_name, session_trade_date, trading_date,
    infer_bar_duration_ms,
)
from app.engines.stats_engine import (
    structure_events, liquidity_statistics, _usable, _day_groups,
    _range_summary, _ci95, _period_completeness, _session_groups, _session_completeness,
)


def _atr(bars, period=14):
    values=[]; prev=None
    for bar in bars:
        tr=bar["high"]-bar["low"]
        if prev is not None:
            tr=max(tr,abs(bar["high"]-prev),abs(bar["low"]-prev))
        values.append(tr); prev=bar["close"]
    return [mean(values[max(0,i-period+1):i+1]) for i in range(len(values))]


def _event_time(bars, index):
    return int(bars[index]["time"] + infer_bar_duration_ms(bars))


def detect_fvg(bars):
    b=_usable(bars); records=[]; duration=infer_bar_duration_ms(b)
    for i in range(2,len(b)):
        left,mid,right=b[i-2],b[i-1],b[i]
        if int(mid["time"])-int(left["time"]) != duration or int(right["time"])-int(mid["time"]) != duration:
            continue
        if right["low"]>left["high"]:
            lo,hi=left["high"],right["low"]; direction="bullish"
        elif right["high"]<left["low"]:
            lo,hi=right["high"],left["low"]; direction="bearish"
        else:
            continue
        width=hi-lo
        if width<=0: continue
        status="open"; mitigation=None; full=None; max_penetration=0.0
        for j,future in enumerate(b[i+1:],start=i+1):
            penetration=((hi-future["low"])/width if direction=="bullish" else (future["high"]-lo)/width)
            max_penetration=max(max_penetration,max(0.0,min(1.0,penetration)))
            if max_penetration>=0.5 and mitigation is None:
                mitigation=to_ny(_event_time(b,j)).isoformat(); status="50%_mitigated"
            if max_penetration>=1:
                full=to_ny(_event_time(b,j)).isoformat(); status="fully_filled"; break
        event_ms=_event_time(b,i)
        future_rows=b[i+1:]
        forward_data_contiguous=all(int(future_rows[j]["time"])-int(future_rows[j-1]["time"])==duration for j in range(1,len(future_rows))) and (not future_rows or int(future_rows[0]["time"])-int(right["time"])==duration)
        records.append({"type":"FVG","direction":direction,"time":to_ny(event_ms).isoformat(),
                        "timestamp":event_ms,"bar_time":right["time"],"bottom":lo,"top":hi,
                        "mid":(lo+hi)/2,"width":width,"max_mitigation_pct":round(max_penetration*100,2),
                        "mitigation_time":mitigation,"fill_time":full,"status":status,
                        "right_censored": full is None,
                        "observation_data_incomplete": full is None and bool(future_rows) and not forward_data_contiguous,
                        "definition":"Three-candle gap requires three consecutive source bars. Future mitigation is scanned only on available bars; unfilled gaps with a truncated or discontinuous observation path are right-censored/data-incomplete."})
    return records


def _confirmed_pivots(bars,left=2,right=2):
    b=_usable(bars); atr=_atr(b); pivots=[]; duration=infer_bar_duration_ms(b)
    for confirm in range(left+right,len(b)):
        idx=confirm-right; win=b[idx-left:idx+right+1]
        if len(win) != left + right + 1 or any(int(win[j]["time"])-int(win[j-1]["time"]) != duration for j in range(1,len(win))):
            continue
        bar=b[idx]
        if bar["high"]==max(x["high"] for x in win) and sum(x["high"]==bar["high"] for x in win)==1:
            pivots.append({"side":"high","price":bar["high"],"idx":idx,"confirm":confirm,"atr":atr[confirm]})
        if bar["low"]==min(x["low"] for x in win) and sum(x["low"]==bar["low"] for x in win)==1:
            pivots.append({"side":"low","price":bar["low"],"idx":idx,"confirm":confirm,"atr":atr[confirm]})
    return b,pivots


def detect_equal_high_low(bars,tolerance_atr=0.10):
    b,pivots=_confirmed_pivots(bars); records=[]
    for side in ("high","low"):
        items=sorted([x for x in pivots if x["side"]==side],key=lambda x:x["confirm"])
        for i in range(1,len(items)):
            first,second=items[i-1],items[i]
            tol=max(second["atr"]*tolerance_atr,1e-10)
            if abs(first["price"]-second["price"])<=tol:
                event_ms=_event_time(b,second["confirm"])
                records.append({"type":"EQH" if side=="high" else "EQL","side":side,
                                "price":(first["price"]+second["price"])/2,
                                "time":to_ny(event_ms).isoformat(),"timestamp":event_ms,
                                "tolerance":tol,"pivot_times":[to_ny(b[first["idx"]]["time"]).isoformat(),
                                                                  to_ny(b[second["idx"]]["time"]).isoformat()],
                                "confirmation_rule":"two confirmed pivots within 0.10 ATR (configurable)"})
    return records


def detect_order_blocks(bars):
    b=_usable(bars); structure=structure_events(b); events=[]
    index={x["time"]:i for i,x in enumerate(b)}
    for event in structure:
        idx=index.get(event["bar_time"])
        if idx is None: continue
        origin=None
        for j in range(idx-1,max(-1,idx-7),-1):
            candle=b[j]
            opposite=(candle["close"]<candle["open"] if event["direction"]=="bullish" else candle["close"]>candle["open"])
            if opposite:
                origin=(j,candle); break
        if origin is None: continue
        j,candle=origin
        top,bottom=candle["high"],candle["low"]
        mitigation=None; breaker=None; state="active"
        for k,future in enumerate(b[idx+1:],start=idx+1):
            if future["low"]<=top and future["high"]>=bottom and mitigation is None:
                mitigation=to_ny(_event_time(b,k)).isoformat(); state="mitigated"
            failed=(future["close"]<bottom if event["direction"]=="bullish" else future["close"]>top)
            if failed:
                breaker=to_ny(_event_time(b,k)).isoformat(); state="breaker"; break
        event_ms=event["time"]
        events.append({"type":"ORDER_BLOCK","direction":event["direction"],"time":event["time_ny"],
                       "timestamp":event_ms,"bar_time":event["bar_time"],
                       "origin_time":to_ny(candle["time"]).isoformat(),"bottom":bottom,"top":top,
                       "state":state,"mitigation_time":mitigation,"breaker_time":breaker,
                       "structure_trigger":event["type"],
                       "definition":"Last opposite candle in the six bars preceding confirmed BOS/MSS; full candle range is used as zone."})
    return events


def _three_drives(bars):
    b,pivots=_confirmed_pivots(bars); out=[]
    for side in ("high","low"):
        items=sorted([x for x in pivots if x["side"]==side],key=lambda x:x["confirm"])
        for i in range(2,len(items)):
            a,c,d=items[i-2:i+1]
            if side=="high":
                trend=a["price"]<c["price"]<d["price"]; direction="bearish"
            else:
                trend=a["price"]>c["price"]>d["price"]; direction="bullish"
            if not trend: continue
            legs=[abs(c["price"]-a["price"]),abs(d["price"]-c["price"])]
            if legs[0]>0 and legs[1]<=legs[0]*1.35:
                event_ms=_event_time(b,d["confirm"])
                out.append({"type":"THREE_DRIVES_CANDIDATE","direction":direction,
                            "time":to_ny(event_ms).isoformat(),"timestamp":event_ms,
                            "prices":[a["price"],c["price"],d["price"]],
                            "definition":"Three progressively higher swing highs or lower swing lows; candidate pattern only, not a trade signal."})
    return out


def _cisd_candidates(bars):
    b=_usable(bars); out=[]; lookback=8; duration=infer_bar_duration_ms(b)
    atr=_atr(b)
    for i in range(2,len(b)):
        prior=b[max(0,i-lookback):i]
        if any(int(b[j]["time"])-int(b[j-1]["time"]) != duration for j in range(max(1,i-lookback),i+1)):
            continue
        last=b[i]
        down=[x for x in prior if x["close"]<x["open"]]
        up=[x for x in prior if x["close"]>x["open"]]
        # Conservative candidate: direction changes and close crosses the open of
        # the latest opposing candle, with a body >= 0.3 local ATR.
        if len(down)>=2 and last["close"]>last["open"] and last["close"]>down[-1]["open"] and (last["close"]-last["open"])>=0.3*atr[i]:
            direction="bullish"; reference=down[-1]["open"]
        elif len(up)>=2 and last["close"]<last["open"] and last["close"]<up[-1]["open"] and (last["open"]-last["close"])>=0.3*atr[i]:
            direction="bearish"; reference=up[-1]["open"]
        else: continue
        event_ms=int(last["time"]+duration)
        out.append({"type":"CISD_CANDIDATE","direction":direction,"time":to_ny(event_ms).isoformat(),
                    "timestamp":event_ms,"reference_open":reference,"close":last["close"],
                    "definition":"Heuristic candidate: close crosses the open of the latest opposing candle after at least two opposing candles, body >= 0.3 ATR."})
    return out


def _judas_candidates(bars,day_start=17,bar_duration_ms=None):
    b=_usable(bars); by_day=_day_groups(b,day_start); by_session=defaultdict(list)
    for x in b:
        by_session[str(session_trade_date(x["time"], day_start)) , session_name(x["time"])].append(x)
    out=[]
    duration=int(bar_duration_ms or infer_bar_duration_ms(b))
    session_quality=_session_completeness(by_session,day_start,duration)
    for day in sorted(by_day):
        asia=by_session.get((day,"Asia"),[])
        if not asia or not session_quality.get((day,"Asia"),{}).get("complete",False): continue
        ah=max(x["high"] for x in asia); al=min(x["low"] for x in asia); width=ah-al
        if width<=0: continue
        candidates=[]
        for sess in ("London","NY AM"):
            start_minute=time_utils.SESSION_WINDOWS[sess][0]
            for x in by_session.get((day,sess),[]):
                local=to_ny(x["time"]); minute=local.hour*60+local.minute
                elapsed=(minute-start_minute)%1440
                if 0<=elapsed<60:
                    candidates.append(x)
        candidates.sort(key=lambda x:x["time"])
        for bar in candidates:
            direction=None
            if bar["high"]>ah and bar["close"]<ah: direction="bearish"
            elif bar["low"]<al and bar["close"]>al: direction="bullish"
            if not direction: continue
            idx=next((i for i,x in enumerate(b) if x["time"]==bar["time"]),None)
            event_ms=int(bar["time"]+duration)
            window_end=event_ms+120*60_000
            expected_count=(120*60_000)//duration if duration and (120*60_000)%duration==0 else 0
            follow=[x for x in (b[idx+1:] if idx is not None else []) if int(x["time"])<window_end]
            expected_times=[event_ms+j*duration for j in range(expected_count)]
            actual_follow_times=[int(x["time"]) for x in follow]
            fully_observed=bool(expected_count and actual_follow_times==expected_times)
            observed_close=int(b[-1]["time"])+duration if b else 0
            right_censored=observed_close<window_end
            observed_bars=min(expected_count,max(0,(min(observed_close,window_end)-event_ms)//duration))
            expected_observed=[event_ms+j*duration for j in range(observed_bars)]
            data_incomplete=actual_follow_times!=expected_observed
            excursion=None
            if fully_observed and follow:
                excursion=(bar["close"]-min(x["low"] for x in follow) if direction=="bearish"
                           else max(x["high"] for x in follow)-bar["close"])
            out.append({"type":"JUDAS_SWING_CANDIDATE","direction":direction,"date":day,
                        "time":to_ny(event_ms).isoformat(),"timestamp":event_ms,
                        "asia_high":ah,"asia_low":al,
                        "follow_through_atr_range":excursion/width if excursion is not None else None,
                        "confirmed_follow_through":(excursion>=0.5*width) if excursion is not None else None,
                        "follow_through_right_censored":right_censored,
                        "follow_through_data_incomplete":data_incomplete,
                        "follow_through_window_minutes":120,
                        "definition":"London/NY opening-hour raid of Asia high/low, close back inside, then >=0.5 Asia-range expansion in the opposite direction within 120 clock minutes. Outcome is null when the full forward window is unavailable; candidate heuristic."})
            break
    return out


def _quarterly_profiles(bars,day_start=17,bar_duration_ms=None):
    """Quarterly context and previous-quarter range breaks; descriptive, not forecast."""
    b=_usable(bars)
    if not b: return []
    duration=int(bar_duration_ms or infer_bar_duration_ms(b))
    days=_day_groups(b,day_start)
    grouped=defaultdict(list)
    for key,rows in days.items():
        # Use the configured trading-date label, not the raw local calendar date
        # of a 17:00 bar, so year/quarter boundaries remain consistent.
        date=datetime.fromisoformat(key).date()
        quarter=(date.month-1)//3+1
        grouped[f"{date.year}-Q{quarter}"].extend(rows)
    keys=sorted(grouped); out=[]
    daily_quality=_period_completeness(days,day_start,"day",duration)
    for i,key in enumerate(keys):
        rows=sorted(grouped[key],key=lambda x:x["time"])
        summary=_range_summary(rows)
        date_keys=sorted({str(trading_date(x["time"],day_start)) for x in rows})
        observed_days_complete=bool(date_keys) and all(daily_quality.get(day,{}).get("complete",False) for day in date_keys)
        complete=(i>0 and i<len(keys)-1 and observed_days_complete)
        prior=[]
        if i>1:
            previous_key=keys[i-1]
            previous_rows=grouped[previous_key]
            previous_dates=sorted({str(trading_date(x["time"],day_start)) for x in previous_rows})
            previous_days_complete=bool(previous_dates) and all(
                daily_quality.get(day,{}).get("complete",False) for day in previous_dates
            )
            # A previous quarter is a valid reference only when it is not an
            # observed edge quarter and all its observed trading days are complete.
            if previous_days_complete and i-1 < len(keys)-1:
                prior=previous_rows
        prev_high=max((x["high"] for x in prior),default=None)
        prev_low=min((x["low"] for x in prior),default=None)
        close=summary["close"]
        shift=("bullish_break_previous_quarter_high" if prev_high is not None and close>prev_high
               else "bearish_break_previous_quarter_low" if prev_low is not None and close<prev_low else "inside_previous_quarter_range")
        out.append({"type":"QUARTERLY_PROFILE","quarter":key,"date":key,"open":summary["open"],
                    "close":close,"high":summary["high"],"low":summary["low"],"range":summary["range"],
                    "high_time":summary["high_time"],"low_time":summary["low_time"],
                    "previous_quarter_high":prev_high,"previous_quarter_low":prev_low,
                    "shift_candidate":shift,"complete_history_period":complete,
                    "all_observed_days_complete":observed_days_complete,
                    "observed_trading_days":len(date_keys),
                    "timestamp":int(rows[-1]["time"]+duration),
                    "time":to_ny(rows[-1]["time"]+duration).isoformat(),
                    "definition":"Quarterly OHLC context; shift candidate compares observed quarter close with previous quarter extremes. Edge quarters are partial. Completeness means all observed day-windows are complete; it cannot prove that an entire broker trading day was not omitted without the broker's market calendar."})
    return out


def _confluence_candidates(bars,day_start,duration,fvgs,equal_pools,order_blocks,structure):
    """Transparent weighted evidence score; explicitly not a probability or entry signal."""
    liquidity=liquidity_statistics(bars,day_start=day_start,bar_duration_ms=duration)
    sweeps=[x for x in liquidity["records"] if x.get("event")=="sweep"]
    out=[]
    horizon60=60*60_000; horizon30=30*60_000
    for sweep in sweeps:
        direction="bullish" if sweep.get("side")=="sell-side" else "bearish"
        ts=int(sweep["timestamp"]); evidence=[{"type":"LIQUIDITY_SWEEP","timestamp":ts,"points":2}]
        mss=next((x for x in structure if x.get("type")=="MSS" and x.get("direction")==direction and ts < x["timestamp"] <= ts+horizon60),None)
        if mss: evidence.append({"type":"DIRECTIONAL_MSS","timestamp":mss["timestamp"],"points":3})
        fvg=next((x for x in fvgs if x.get("direction")==direction and ts < x["timestamp"] <= ts+horizon30),None)
        if fvg: evidence.append({"type":"DIRECTIONAL_FVG","timestamp":fvg["timestamp"],"points":1})
        ob=next((x for x in order_blocks if x.get("direction")==direction and ts < x["timestamp"] <= ts+horizon60),None)
        if ob: evidence.append({"type":"DIRECTIONAL_ORDER_BLOCK","timestamp":ob["timestamp"],"points":1})
        pool_type="EQL" if direction=="bullish" else "EQH"
        pool=next((x for x in equal_pools if x.get("type")==pool_type and ts-5*60_000 <= x["timestamp"] <= ts+horizon60),None)
        if pool: evidence.append({"type":"ALIGNED_EQUAL_LIQUIDITY_POOL","timestamp":pool["timestamp"],"points":1})
        score=sum(x["points"] for x in evidence)
        # A confluence candidate is only confirmed when its last supporting item
        # is known. Never timestamp it back at the sweep if later evidence is used.
        confirmed_ms=max(int(x["timestamp"]) for x in evidence)
        out.append({"type":"CONFLUENCE_CANDIDATE","direction":direction,
                    "time":to_ny(confirmed_ms).isoformat(),"timestamp":confirmed_ms,
                    "sweep_time":sweep["time"],"sweep_timestamp":ts,
                    "level_type":sweep["level_type"],"level":sweep["level"],
                    "score":score,"max_score":8,"evidence":evidence,
                    "classification":"heuristic evidence score; not probability, trade recommendation or calibrated signal",
                    "definition":"2 points for sweep, 3 for direction-aligned MSS within 60m, 1 each for aligned FVG within 30m, OB within 60m and EQH/EQL liquidity pool within a 5m-before/60m-after window. Event time is the last supporting evidence timestamp."})
    return sorted(out,key=lambda x:(-x["score"],-x["timestamp"]))[:2000]


def advanced_ict_statistics(bars,day_start=17,bar_duration_ms=None):
    b=_usable(bars)
    if not b:
        return {"metrics":{},"fvg_records":[],"liquidity_pools":[],"order_blocks":[],"cbdr_records":[],"silver_bullet_records":[],"po3_records":[],"ipda_records":[],"judas_records":[],"cisd_records":[],"three_drive_records":[],"confluence_records":[],"quarterly_records":[]}
    fvgs=detect_fvg(b); eq=detect_equal_high_low(b); obs=detect_order_blocks(b)
    structure=structure_events(b); daily_groups=_day_groups(b,day_start)
    duration=int(bar_duration_ms or infer_bar_duration_ms(b))
    day_quality=_period_completeness(daily_groups,day_start,"day",duration)
    daily_all=[{"date":key,**_range_summary(rows),**day_quality.get(key,{"complete":True})} for key,rows in sorted(daily_groups.items())]
    # ADR/IPDA baselines exclude truncated first/last trading days.
    daily=[x for x in daily_all if x.get("complete",True)]
    adr={}
    for n in (5,20,50):
        sample=[x["range"] for x in daily[-n:]]
        adr[str(n)]={"value":mean(sample) if sample else None,"samples":len(sample),"complete_history_only":True}
    # Use trailing completed observations before the latest bar for IPDA-style range context.
    ipda=[]
    latest=b[-1]
    for n in (20,40,60):
        sample=daily[-n:]
        if not sample: continue
        high=max(x["high"] for x in sample); low=min(x["low"] for x in sample); eqp=(high+low)/2
        ipda.append({"lookback_days":n,"high":high,"low":low,"equilibrium":eqp,
                     "last_price":latest["close"],"position":"premium" if latest["close"]>eqp else "discount" if latest["close"]<eqp else "equilibrium",
                     "range":high-low,"samples":len(sample),"definition":"Rolling observed trading-day high/low range; descriptive IPDA-style context, not a claim about institutional dealing algorithms."})
    latest_range=ipda[0] if ipda else None
    dealing_range={"high":latest_range["high"] if latest_range else None,
                   "low":latest_range["low"] if latest_range else None,
                   "equilibrium":latest_range["equilibrium"] if latest_range else None,
                   "last_price_position":latest_range["position"] if latest_range else "unknown"}

    # CBDR is a New York calendar-clock window 14:00–20:00. Do not group it by
    # the Forex 17:00 trading-day boundary (that would split one CBDR in two).
    cbdr=defaultdict(list)
    for x in b:
        dt=to_ny(x["time"])
        if 14<=dt.hour<20: cbdr[dt.date().isoformat()].append(x)
    cbdr_rows=[]
    for day,rows in sorted(cbdr.items()):
        s=_range_summary(rows)
        first=to_ny(rows[0]["time"]); last_close=to_ny(rows[-1]["time"]+duration)
        start_dt=datetime.combine(first.date(), dt_time(14,0), tzinfo=first.tzinfo)
        end_dt=datetime.combine(first.date(), dt_time(20,0), tzinfo=first.tzinfo)
        start_ms=int(start_dt.timestamp()*1000); end_ms=int(end_dt.timestamp()*1000)
        span=end_ms-start_ms
        expected_bars=span//duration if span>0 and span%duration==0 else 0
        expected_times=[start_ms+j*duration for j in range(expected_bars)]
        actual_times=[int(x["time"]) for x in rows]
        coverage=(len(set(actual_times).intersection(expected_times))/expected_bars) if expected_bars else 0.0
        complete=bool(expected_bars and actual_times==expected_times)
        cbdr_rows.append({"date":day,"high":s["high"],"low":s["low"],"range":s["range"],
                          "start":first.isoformat(),"end":last_close.isoformat(),"complete":complete,
                          "expected_bars":expected_bars,"observed_bars":len(rows),"coverage_ratio":round(coverage,6),
                          "has_internal_gaps":bool(expected_bars and not complete and actual_times and actual_times[0]==start_ms and actual_times[-1]+duration==end_ms),
                          "definition":"New York calendar-day 14:00–20:00 window. Completeness requires every expected source bar with no internal gaps; instrument-specific market hours may differ."})

    silver=[]
    for fvg in fvgs:
        dt=to_ny(fvg["timestamp"])
        label=next((name for hour,name in ((3,"London SB"),(10,"NY AM SB"),(14,"NY PM SB")) if dt.hour==hour),None)
        if label:
            silver.append({**fvg,"silver_bullet_window":label,
                           "definition":"FVG formed during the configured 03:00–04:00, 10:00–11:00 or 14:00–15:00 New York window; a window match alone is not a complete Silver Bullet setup."})

    # PO3/AMD candidates: Asia accumulation, boundary manipulation, opposite-side expansion.
    session_map=defaultdict(lambda:{"Asia":[],"London":[],"NY AM":[],"London Close":[],"NY PM":[]})
    for x in b:
        s=session_name(x["time"])
        if s in {"Asia","London","NY AM","London Close","NY PM"}:
            session_map[str(session_trade_date(x["time"], day_start))][s].append(x)
    po3=[]
    session_groups=_session_groups(b,day_start)
    session_quality=_session_completeness(session_groups,day_start,duration)
    for day,parts in sorted(session_map.items()):
        asia=parts["Asia"]
        if not asia or not session_quality.get((day,"Asia"),{}).get("complete",False): continue
        ah=max(x["high"] for x in asia); al=min(x["low"] for x in asia)
        later=sorted(parts["London"]+parts["NY AM"]+parts["London Close"]+parts["NY PM"],key=lambda x:x["time"])
        for i,x in enumerate(later):
            event_ms=int(x["time"]+duration)
            if x["high"]>ah and x["close"]<ah:
                dist=next((y for y in later[i+1:] if y["close"]<al),None)
                confirmed_ms=int(dist["time"]+duration) if dist else None
                stamp=confirmed_ms or event_ms
                po3.append({"date":day,"phase":"manipulation_buy_side","distribution":"bearish" if dist else "unconfirmed",
                            "candidate_time":to_ny(event_ms).isoformat(),"confirmation_time":to_ny(confirmed_ms).isoformat() if confirmed_ms else None,
                            "time":to_ny(stamp).isoformat(),"timestamp":stamp,
                            "asia_high":ah,"asia_low":al,"definition":"PO3/AMD candidate: Asia range, buy-side raid/reclaim, then later close below Asia low. Confirmed candidate timestamp is the distribution close; unconfirmed candidate timestamp is the manipulation close."}); break
            if x["low"]<al and x["close"]>al:
                dist=next((y for y in later[i+1:] if y["close"]>ah),None)
                confirmed_ms=int(dist["time"]+duration) if dist else None
                stamp=confirmed_ms or event_ms
                po3.append({"date":day,"phase":"manipulation_sell_side","distribution":"bullish" if dist else "unconfirmed",
                            "candidate_time":to_ny(event_ms).isoformat(),"confirmation_time":to_ny(confirmed_ms).isoformat() if confirmed_ms else None,
                            "time":to_ny(stamp).isoformat(),"timestamp":stamp,
                            "asia_high":ah,"asia_low":al,"definition":"PO3/AMD candidate: Asia range, sell-side raid/reclaim, then later close above Asia high. Confirmed candidate timestamp is the distribution close; unconfirmed candidate timestamp is the manipulation close."}); break

    judas=_judas_candidates(b,day_start,duration); cisd=_cisd_candidates(b); three_drives=_three_drives(b)
    quarterly_records=_quarterly_profiles(b,day_start,duration)
    confluence_records=_confluence_candidates(b,day_start,duration,fvgs,eq,obs,structure)
    return {
        "metrics":{"fvg_count":len(fvgs),"fvg_mitigated_50":sum(x["mitigation_time"] is not None for x in fvgs),
                    "fvg_fully_filled":sum(x["fill_time"] is not None for x in fvgs),
                    "equal_high_low_count":len(eq),"order_blocks":len(obs),
                    "breaker_blocks":sum(x["state"]=="breaker" for x in obs),"adr":adr,
                    "dealing_range":dealing_range,"ipda_ranges":len(ipda),"cbdr_days":len(cbdr_rows),
                    "silver_bullet_fvg_count":len(silver),"po3_candidates":len(po3),
                    "judas_swing_candidates":len(judas),"cisd_candidates":len(cisd),
                    "three_drive_candidates":len(three_drives),
                    "confluence_candidates":len(confluence_records),
                    "quarterly_profiles":len(quarterly_records),
                    "complete_daily_samples":len(daily),"incomplete_daily_excluded":len(daily_all)-len(daily)},
        "fvg_records":fvgs,"liquidity_pools":eq,"order_blocks":obs,"cbdr_records":cbdr_rows,
        "silver_bullet_records":silver,"po3_records":po3,"ipda_records":ipda,
        "judas_records":judas,"cisd_records":cisd,"three_drive_records":three_drives,
        "confluence_records":confluence_records,"quarterly_records":quarterly_records,
        "methodology":"ICT definitions vary by practitioner. EQH/EQL, FVG, OB/Breaker and swing breaks use explicit mechanical proxies in code. Silver Bullet, PO3/AMD, Judas Swing, CISD, Three Drives and IPDA records are labelled candidates/descriptive context; tune thresholds/session windows for the instrument before treating them as research hypotheses."}


def smt_divergence(primary:list[dict],secondary:list[dict]):
    a=_usable(primary); b=_usable(secondary)
    bmap={x["time"]:x for x in b}
    aligned=[(x,bmap[x["time"]]) for x in a if x["time"] in bmap]
    if len(aligned)<20:
        return {"metrics":{"samples":len(aligned),"status":"insufficient_aligned_history"},"records":[]}
    lookback=20; records=[]
    for i in range(lookback,len(aligned)):
        a0,a1=aligned[i-lookback][0],aligned[i][0]
        b0,b1=aligned[i-lookback][1],aligned[i][1]
        if a1["high"]>a0["high"] and b1["high"]<=b0["high"]:
            kind="bearish_smt"
        elif a1["low"]<a0["low"] and b1["low"]>=b0["low"]:
            kind="bullish_smt"
        else: continue
        event_ms=int(aligned[i][0]["time"]+infer_bar_duration_ms(a))
        records.append({"type":kind,"time":to_ny(event_ms).isoformat(),"timestamp":event_ms,
                        "primary_high_change":a1["high"]-a0["high"],
                        "secondary_high_change":b1["high"]-b0["high"]})
    return {"metrics":{"samples":len(aligned),"divergences":len(records),
                        "alignment":"exact UTC timestamps","definition":"rolling 20-bar relative swing divergence candidate"},
            "records":records}
