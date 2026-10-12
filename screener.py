"""Xiaoming V3: free A-share screening; research signals, not orders."""
import json, os, time, sys, signal
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd
import akshare as ak

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
OUT.mkdir(exist_ok=True)
NOW = datetime.now(ZoneInfo('Asia/Shanghai'))

def fetch(fn, attempts=3):
    for i in range(attempts):
        try:
            x = fn()
            if x is None or len(x) == 0: raise ValueError('empty response')
            return x
        except Exception:
            if i == attempts-1: raise
            time.sleep(2*(i+1))

class RequestTimeout(Exception):
    pass

def bounded(fn, seconds=9):
    def alarm_handler(signum, frame):
        raise RequestTimeout('request exceeded '+str(seconds)+'s')
    previous=signal.signal(signal.SIGALRM,alarm_handler)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous)

def daily(code):
    start=(NOW-pd.Timedelta(days=110)).strftime('%Y%m%d')
    end=NOW.strftime('%Y%m%d')
    symbol=('sh' if code.startswith('6') else 'sz')+code
    providers=[
        ('sina',lambda:ak.stock_zh_a_daily(symbol=symbol,start_date=start,end_date=end,adjust='')),
        ('eastmoney',lambda:ak.stock_zh_a_hist(symbol=code,period='daily',start_date=start,end_date=end,adjust='')),
    ]
    failures=[]
    for name,fn in providers:
        try:
            df=bounded(fn,seconds=9)
            if df is None or len(df)<35:
                raise ValueError('insufficient bars')
            df=df.rename(columns={'日期':'date','开盘':'open','收盘':'close','最高':'high','最低':'low',
                                  '成交量':'volume','成交额':'turnover'})
            if 'date' not in df.columns and df.index.name in ('date','日期'):
                df=df.reset_index()
            required={'date','open','close','high','low','volume'}
            if not required.issubset(df.columns):
                raise ValueError('missing K-line columns '+str(required-set(df.columns)))
            for col in ['open','close','high','low','volume']:
                df[col]=pd.to_numeric(df[col],errors='coerce')
            df=df.dropna(subset=['close','high','low','volume']).sort_values('date')
            df=df[pd.to_datetime(df['date']).dt.date < NOW.date()]
            if len(df)<35:
                raise ValueError('fewer than 35 completed daily bars')
            return df,name
        except Exception as exc:
            failures.append(name+': '+str(exc)[:90])
    raise RuntimeError(' | '.join(failures))

def assess(df):
    # Strictly use completed daily bars. Never interpret live snapshot as a closed bar.
    if len(df) < 35: return None
    c = df['close']; v = df['volume']; h = df['high']; lo = df['low']
    last = float(c.iloc[-1]); ma20=float(c.tail(20).mean()); ma10=float(c.tail(10).mean())
    prior_high=float(h.iloc[-21:-1].max()); support=float(lo.tail(10).min())
    vol_ratio=float(v.iloc[-1]/max(v.iloc[-21:-1].mean(),1))
    extension=last/ma20-1
    distance=last/prior_high-1
    trend=last>ma20 and ma10>=ma20
    # Near prior high or controlled pullback, not excessively extended.
    near_break=-0.065<=distance<=0.025
    controlled=extension<=0.13 and extension>=-0.02
    risk=(last-support)/last if last>support else 1
    upside=(prior_high*1.10-last)/last
    rr=upside/risk if risk>0 else 0
    passed=trend and near_break and controlled and risk<=0.09 and rr>=2
    score=round(35*int(trend)+20*int(near_break)+15*int(controlled)
                +15*min(vol_ratio/1.5,1)+15*min(rr/3,1),1)
    return dict(close=round(last,2), ma20=round(ma20,2), prior_high=round(prior_high,2),
      support=round(support,2), vol_ratio=round(vol_ratio,2), risk_pct=round(risk*100,2),
      estimated_rr=round(rr,2), score=score, passed=bool(passed),
      trigger=f'放量站稳 {prior_high:.2f}（以实时盘口再次确认）',
      invalidation=f'放量跌破 {support:.2f} 且无法收回', bar_date=str(df['date'].iloc[-1]))

def snapshot():
    issues = []
    for name, fn in [('eastmoney', ak.stock_zh_a_spot_em), ('sina', ak.stock_zh_a_spot)]:
        try:
            d = fetch(fn, attempts=2).copy()
            if name == 'sina':
                d = d.rename(columns={'code':'代码','name':'名称','trade':'最新价','amount':'成交额'})
                d['代码'] = d['代码'].astype(str).str.extract(r'([0-9]{6})$', expand=False)
            required = {'代码','名称','最新价','成交额'}
            if not required.issubset(d.columns):
                raise ValueError('Missing columns: '+str(required-set(d.columns)))
            d['最新价'] = pd.to_numeric(d['最新价'], errors='coerce')
            d['成交额'] = pd.to_numeric(d['成交额'], errors='coerce')
            d = d[d['代码'].astype(str).str.fullmatch(r'(60|00)[0-9]{4}') & d['最新价'].between(0.01,100)].copy()
            if len(d) < 300:
                raise ValueError('Too few eligible symbols: '+str(len(d)))
            return d, name, issues
        except Exception as e:
            issues.append(name+': '+repr(e)[:180])
    raise RuntimeError('All snapshot feeds failed: '+' | '.join(issues))

def group_by_name(name):
    for group in ('银行','证券','保险','电力','石油','石化'):
        if group in name: return group
    return '未分类'

def main():
    errors=[]; scanned=0; qualified=[]; provider_counts={}
    spot=None; source=None; fatal=False
    limit=min(150,max(1,int(os.getenv('MAX_HISTORY_SYMBOLS','100'))))
    try:
        spot,source,warnings=snapshot()
        errors.extend(warnings)
    except Exception as exc:
        errors.append('全市场行情失败: '+repr(exc))
        fatal=True
    # An unavailable spot feed is a hard stop; do not substitute an old watchlist.
    if spot is not None:
        # Full-market snapshot covers all eligible main-board symbols.
        # Historical fetches are capped for public endpoint rate limits;
        # do NOT claim full-market technical coverage.
        spot=spot.sort_values('成交额',ascending=False, key=lambda x:pd.to_numeric(x,errors='coerce').fillna(0))
        for _,r in spot.head(limit).iterrows():
            code=str(r['代码'])
            try:
                bars,provider=daily(code)
                result=assess(bars); scanned+=1
                provider_counts[provider]=provider_counts.get(provider,0)+1
                if result and result['passed']:
                    qualified.append({'code':code,'name':str(r['名称']),'group':group_by_name(str(r['名称'])),'snapshot_price':round(float(r['最新价']),2),**result})
            except Exception as exc:
                errors.append(f'{code}: {str(exc)[:100]}')
            time.sleep(float(os.getenv('FETCH_DELAY','0.35')))
    target=0 if spot is None else min(limit,len(spot))
    minimum=max(5,int(target*0.8)) if target else 0
    if spot is not None and scanned<minimum:
        fatal=True; errors.append(f'历史K线覆盖率不足：{scanned}/{target}，最低要求{minimum}')
    qualified.sort(key=lambda x:x['score'],reverse=True)
    diversified=[]; counts={}
    for item in qualified:
        group=item['group']
        if group!='未分类' and counts.get(group,0)>=2: continue
        diversified.append(item)
        counts[group]=counts.get(group,0)+1
    market_stats={} if spot is None else {'eligible_count':len(spot),'median_price':round(float(spot['最新价'].median()),2)}
    # Technical candidates are NOT verified trade entries; sector/news and intraday confirmation pending.
    report={'generated_at':NOW.isoformat(),'status':'DATA_FAILED' if fatal else ('partial' if errors else 'ok'),
        'universe_count':0 if spot is None else len(spot),'snapshot_source':source,
        'historical_symbols_checked':scanned,'market_stats':market_stats,'sector_verified':False,'capital_flow_verified':False,'historical_target':target,'historical_minimum':minimum,'historical_sources':provider_counts,'historical_limit':limit,
        'coverage':'全市场快照 + 成交额前N只历史K线技术复核；不是全市场逐股K线覆盖',
        'data_warning':'免费行情可能延迟/限流；K线末根可能是当日未收盘数据，盘中不得视为已确认日K',
        'candidates':diversified[:6],'decision_status':'WAIT_VERIFY','grouping_method':'name_only_unverified','errors':errors[:30],
        'decision':'观察名单，不构成买入指令；需核验板块、催化、分钟量价、止损和实时盘口'}
    (OUT/'latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 小明选股 V3.4｜集中度约束技术预筛报告',f'生成时间：{report["generated_at"]}',
        f'状态：{report["status"]}；快照范围：{report["universe_count"]}；K线检查：{scanned}/{target}；K线来源：{provider_counts}；板块和资金尚未验证',
        '',f'**覆盖说明：** {report["coverage"]}',f'**风险提示：** {report["data_warning"]}',
        '','## 技术候选（不是买入信号）']
    lines.append('决策：等待验证；名称分组最多2只，未分类股票无法保证行业分散。')
    if not diversified: lines.append('0只：未发现通过条件的候选，或数据不完整。')
    for x in diversified[:6]:
        lines.append(f'- **{x["name"]} {x["code"]}**｜K线日期 {x["bar_date"]}｜参考价 {x["close"]}｜评分 {x["score"]}｜前高 {x["prior_high"]}｜支撑 {x["support"]}｜预估盈亏比 {x["estimated_rr"]}｜{x["trigger"]}｜失效：{x["invalidation"]}')
    lines+=['','## 运行问题']+[f'- {e}' for e in errors[:15]] if errors else ['','运行错误：无（不代表行情无延迟）。']
    (OUT/'latest.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('\n'.join(lines))
    if fatal:
        print('DATA_FAILED: market data unavailable',file=sys.stderr)
        sys.exit(2)

if __name__=='__main__': main()
