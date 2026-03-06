"""
Base de datos SQLite con SQLAlchemy
"""

from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text, Boolean, func
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timedelta
import json
from config import DATABASE_URL

Base = declarative_base()


class OptionsSnapshot(Base):
    __tablename__ = "options_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    current_price = Column(Float)
    call_volume = Column(Integer)
    put_volume = Column(Integer)
    call_open_interest = Column(Integer)
    put_open_interest = Column(Integer)
    put_call_ratio_volume = Column(Float)
    put_call_ratio_oi = Column(Float)
    avg_call_iv = Column(Float)
    avg_put_iv = Column(Float)
    historical_volatility = Column(Float)
    iv_skew = Column(Float)
    market_sentiment = Column(String(20))


class AlertRecord(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    alert_type = Column(String(50))
    message = Column(Text)
    severity = Column(String(10))
    acknowledged = Column(Boolean, default=False)


class UnusualActivity(Base):
    __tablename__ = "unusual_activity"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    option_type = Column(String(4))
    strike = Column(Float)
    expiration = Column(String(10))
    volume = Column(Integer)
    open_interest = Column(Integer)
    vol_oi_ratio = Column(Float)
    implied_volatility = Column(Float)
    last_price = Column(Float)


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    cycle_number = Column(Integer)
    tickers_analyzed = Column(Integer)
    alerts_generated = Column(Integer)
    unusual_activities = Column(Integer)
    market_sentiment = Column(String(20))
    claude_analysis = Column(Text)
    execution_time_seconds = Column(Float)


class BacktestSignal(Base):
    __tablename__ = "backtest_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    signal_type = Column(String(50))
    direction = Column(String(10))
    price_at_signal = Column(Float)
    price_after_1d = Column(Float, nullable=True)
    price_after_3d = Column(Float, nullable=True)
    price_after_7d = Column(Float, nullable=True)
    outcome = Column(String(20), nullable=True)
    details = Column(Text, nullable=True)


class OptionsDatabase:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL, echo=False)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        self.cycle_count = self._get_cycle_count()

    def _get_cycle_count(self):
        last = self.session.query(func.max(AgentLog.cycle_number)).scalar()
        return (last or 0)

    def save_snapshot(self, analysis):
        for ticker, data in analysis.get("summary", {}).items():
            s = OptionsSnapshot(
                timestamp=datetime.fromisoformat(analysis["timestamp"]),
                ticker=ticker, current_price=data.get("current_price", 0),
                call_volume=data.get("call_volume", 0), put_volume=data.get("put_volume", 0),
                call_open_interest=data.get("call_open_interest", 0),
                put_open_interest=data.get("put_open_interest", 0),
                put_call_ratio_volume=data.get("put_call_ratio_volume", 0),
                put_call_ratio_oi=data.get("put_call_ratio_oi", 0),
                avg_call_iv=data.get("avg_call_iv", 0), avg_put_iv=data.get("avg_put_iv", 0),
                historical_volatility=data.get("historical_volatility", 0),
                iv_skew=data.get("iv_skew", 0),
                market_sentiment=analysis.get("market_sentiment", ""))
            self.session.add(s)
        self.session.commit()

    def get_ticker_history(self, ticker, days=30):
        cutoff = datetime.utcnow() - timedelta(days=days)
        snaps = self.session.query(OptionsSnapshot).filter(
            OptionsSnapshot.ticker == ticker, OptionsSnapshot.timestamp >= cutoff
        ).order_by(OptionsSnapshot.timestamp.asc()).all()
        return [{"timestamp": s.timestamp.isoformat(), "price": s.current_price,
                 "call_volume": s.call_volume, "put_volume": s.put_volume,
                 "pcr_volume": s.put_call_ratio_volume, "pcr_oi": s.put_call_ratio_oi,
                 "call_iv": s.avg_call_iv, "put_iv": s.avg_put_iv,
                 "hv": s.historical_volatility, "iv_skew": s.iv_skew} for s in snaps]

    def get_all_tickers_latest(self):
        subq = self.session.query(
            OptionsSnapshot.ticker, func.max(OptionsSnapshot.timestamp).label("max_ts")
        ).group_by(OptionsSnapshot.ticker).subquery()
        latest = self.session.query(OptionsSnapshot).join(
            subq, (OptionsSnapshot.ticker == subq.c.ticker) & (OptionsSnapshot.timestamp == subq.c.max_ts)
        ).all()
        return [{"ticker": s.ticker, "timestamp": s.timestamp.isoformat(),
                 "price": s.current_price, "pcr_volume": s.put_call_ratio_volume,
                 "call_iv": s.avg_call_iv, "put_iv": s.avg_put_iv,
                 "iv_skew": s.iv_skew, "sentiment": s.market_sentiment} for s in latest]

    def save_alerts(self, alerts):
        for a in alerts:
            self.session.add(AlertRecord(
                ticker=a.get("ticker", ""), alert_type=a.get("type", ""),
                message=a.get("message", ""), severity=a.get("severity", "medium")))
        self.session.commit()

    def get_recent_alerts(self, hours=24):
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        alerts = self.session.query(AlertRecord).filter(
            AlertRecord.timestamp >= cutoff).order_by(AlertRecord.timestamp.desc()).all()
        return [{"id": a.id, "timestamp": a.timestamp.isoformat(), "ticker": a.ticker,
                 "type": a.alert_type, "message": a.message, "severity": a.severity,
                 "acknowledged": a.acknowledged} for a in alerts]

    def save_unusual_activity(self, activities):
        for act in activities:
            self.session.add(UnusualActivity(
                ticker=act.get("ticker", ""), option_type=act.get("type", ""),
                strike=act.get("strike", 0), expiration=act.get("expiration", ""),
                volume=act.get("volume", 0), open_interest=act.get("open_interest", 0),
                vol_oi_ratio=act.get("vol_oi_ratio", 0),
                implied_volatility=act.get("implied_volatility", 0),
                last_price=act.get("last_price", 0)))
        self.session.commit()

    def get_unusual_history(self, ticker=None, days=7):
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = self.session.query(UnusualActivity).filter(UnusualActivity.timestamp >= cutoff)
        if ticker:
            q = q.filter(UnusualActivity.ticker == ticker)
        acts = q.order_by(UnusualActivity.timestamp.desc()).limit(50).all()
        return [{"timestamp": a.timestamp.isoformat(), "ticker": a.ticker,
                 "type": a.option_type, "strike": a.strike, "expiration": a.expiration,
                 "volume": a.volume, "oi": a.open_interest,
                 "vol_oi_ratio": a.vol_oi_ratio, "iv": a.implied_volatility} for a in acts]

    def save_agent_log(self, analysis, claude_response, exec_time):
        self.cycle_count += 1
        self.session.add(AgentLog(
            cycle_number=self.cycle_count,
            tickers_analyzed=len(analysis.get("tickers_analyzed", [])),
            alerts_generated=len(analysis.get("alerts", [])),
            unusual_activities=len(analysis.get("unusual_activity", [])),
            market_sentiment=analysis.get("market_sentiment", ""),
            claude_analysis=claude_response[:5000], execution_time_seconds=exec_time))
        self.session.commit()

    def save_backtest_signal(self, signal):
        r = BacktestSignal(
            ticker=signal.get("ticker", ""), signal_type=signal.get("signal_type", ""),
            direction=signal.get("direction", ""), price_at_signal=signal.get("price_at_signal", 0),
            details=json.dumps(signal.get("details", {})))
        self.session.add(r)
        self.session.commit()
        return r.id

    def update_backtest_outcome(self, signal_id, price_1d=None, price_3d=None, price_7d=None, outcome=None):
        s = self.session.query(BacktestSignal).filter_by(id=signal_id).first()
        if s:
            if price_1d is not None: s.price_after_1d = price_1d
            if price_3d is not None: s.price_after_3d = price_3d
            if price_7d is not None: s.price_after_7d = price_7d
            if outcome: s.outcome = outcome
            self.session.commit()

    def get_backtest_signals(self, ticker=None, days=30):
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = self.session.query(BacktestSignal).filter(BacktestSignal.timestamp >= cutoff)
        if ticker:
            q = q.filter(BacktestSignal.ticker == ticker)
        sigs = q.order_by(BacktestSignal.timestamp.desc()).all()
        return [{"id": s.id, "timestamp": s.timestamp.isoformat(), "ticker": s.ticker,
                 "signal_type": s.signal_type, "direction": s.direction,
                 "price_at_signal": s.price_at_signal, "price_after_1d": s.price_after_1d,
                 "price_after_3d": s.price_after_3d, "price_after_7d": s.price_after_7d,
                 "outcome": s.outcome,
                 "details": json.loads(s.details) if s.details else {}} for s in sigs]

    def get_database_stats(self):
        return {
            "total_snapshots": self.session.query(OptionsSnapshot).count(),
            "total_alerts": self.session.query(AlertRecord).count(),
            "total_unusual": self.session.query(UnusualActivity).count(),
            "total_cycles": self.session.query(AgentLog).count(),
            "total_signals": self.session.query(BacktestSignal).count(),
            "unique_tickers": self.session.query(func.count(func.distinct(OptionsSnapshot.ticker))).scalar() or 0,
        }

    def close(self):
        self.session.close()
