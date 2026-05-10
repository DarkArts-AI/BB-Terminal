import os
import json
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import psycopg
from jinja2 import Environment, FileSystemLoader
import markdown
from weasyprint import HTML
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

TEMPLATE_DIR = Path(__file__).parent / "templates"
REPORT_DIR = Path(__file__).parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)

from env_config import CMV4_DSN

report_router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))

SPEAKER_MAP = {
    "market_analyst": ("MKT", "Market Analyst", ""),
    "fundamentals_analyst": ("FUND", "Fundamentals Analyst", ""),
    "news_analyst": ("NEWS", "News Analyst", ""),
    "social_media_analyst": ("SENT", "Sentiment Analyst", ""),
    "sentiment_analyst": ("SENT", "Sentiment Analyst", ""),
    "research_synthesis": ("MGR", "Research Manager", "manager"),
    "bull": ("BULL", "Bull Researcher", "bull"),
    "bear": ("BEAR", "Bear Researcher", "bear"),
    "research_manager": ("MGR", "Research Manager", "manager"),
    "trader": ("TRADE", "Trader", "trader"),
    "aggressive": ("AGG", "Aggressive Debater", "aggressive"),
    "conservative": ("CON", "Conservative Debater", "conservative"),
    "neutral": ("NEU", "Neutral Debater", "neutral"),
    "portfolio_manager": ("PM", "Portfolio Manager", "manager"),
    "risk_management": ("RISK", "Risk Manager", "neutral"),
    "lifesci_analyst": ("LIFE", "Life Sciences Analyst", ""),
    "lifesci": ("LIFE", "Life Sciences Monitor", ""),
    "screen": ("SCR", "Universe Screener", ""),
}


def get_speaker(role):
    key = role.lower().replace(" ", "_").replace("-", "_")
    label, speaker, css = SPEAKER_MAP.get(key, (role[:4].upper(), role, ""))
    return label, speaker, css


def flatten_content(content):
    """Convert structured stage output into readable markdown."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return str(content)

    skip_keys = {
        'source', 'agent', 'model', 'llm_model', 'timestamp', 'ts',
        'llm_metrics', 'llm_fallback', 'screen_data',
    }

    # Screen candidate — format as investment brief
    if 'ticker' in content and 'rating' in content and 'bull_case' in content:
        return _format_screen_candidate(content)

    # LifeSci catalyst profile
    if 'total_score' in content or 'score_30d' in content:
        return _format_lifesci_profile(content)

    # AgentReport with 'report' key
    if 'report' in content and isinstance(content['report'], str):
        return content['report']

    # Bull/Bear debate history
    if 'full_history' in content:
        return _format_debate_history(content)

    # Risk debate
    if 'aggressive_history' in content:
        return _format_risk_debate(content)

    # Generic dict fallback — render as labeled sections
    parts = []
    for k, v in content.items():
        if k.lower() in skip_keys:
            continue
        label = k.replace('_', ' ').title()
        if isinstance(v, str) and len(v) > 50:
            parts.append(f"**{label}:**\n{v}")
        elif isinstance(v, list):
            if v and isinstance(v[0], dict):
                for item in v[:10]:
                    parts.append(_format_nested_item(item))
            else:
                parts.append(f"**{label}:** {', '.join(str(x) for x in v)}")
        elif isinstance(v, dict):
            sub_parts = [f"  - {k2}: {v2}" for k2, v2 in v.items() if k2.lower() not in skip_keys]
            if sub_parts:
                parts.append(f"**{label}:**\n" + "\n".join(sub_parts))
        elif v is not None:
            parts.append(f"**{label}:** {v}")
    return "\n\n".join(parts) if parts else str(content)


def _format_screen_candidate(data: dict) -> str:
    """Format a universe screener candidate as a readable brief."""
    ticker = data.get('ticker', '?')
    rating = data.get('rating', '?')
    conviction = data.get('conviction', '?')
    target = data.get('target_price', '?')
    upside = data.get('upside_pct', '?')
    sd = data.get('screen_data', {})

    lines = [
        f"### {ticker} — {sd.get('name', ticker)}",
        f"**Rating:** {rating} | **Conviction:** {conviction}/10 | **Target:** ${target} ({upside}% upside)",
        "",
        f"**Price:** ${sd.get('current_price', '?')} | **52W Low:** ${sd.get('low_52wk', '?')} ({sd.get('pct_above_low', '?')}% above) | **52W High:** ${sd.get('high_52wk', '?')}",
        f"**Sector:** {sd.get('sector', 'N/A')} | **Industry:** {sd.get('industry', 'N/A')}",
        f"**P/E:** {sd.get('pe_ratio', 'N/A')} | **Fwd P/E:** {sd.get('forward_pe', 'N/A')} | **Mkt Cap:** ${sd.get('market_cap', 0)/1e9:.1f}B" if sd.get('market_cap') else "",
        "",
    ]

    if data.get('bull_case'):
        lines.append(f"**Bull Case:** {data['bull_case']}")
    if data.get('bear_case'):
        lines.append(f"**Bear Case:** {data['bear_case']}")
    if data.get('catalyst'):
        lines.append(f"**Key Catalyst:** {data['catalyst']}")
    if data.get('risk'):
        lines.append(f"**Primary Risk:** {data['risk']}")
    if data.get('rationale'):
        lines.append(f"\n**Thesis:** {data['rationale']}")

    return "\n".join(line for line in lines if line is not None)


def _format_lifesci_profile(data: dict) -> str:
    """Format a life sciences catalyst profile."""
    lines = []

    if data.get('total_score') is not None:
        lines.append(f"**Catalyst Score:** {data['total_score']:.1f}")
    scores = []
    for window in ['score_30d', 'score_60d', 'score_90d']:
        if data.get(window) is not None:
            label = window.replace('score_', '').upper()
            scores.append(f"{label}: {data[window]:.1f}")
    if scores:
        lines.append(f"**Window Scores:** {' | '.join(scores)}")

    if data.get('binary_event_risk'):
        lines.append(f"**Binary Event Risk:** {data['binary_event_risk']}")
    if data.get('highest_probability_event'):
        lines.append(f"**Top Event:** {data['highest_probability_event']}")

    events = data.get('events', [])
    if events:
        lines.append("\n**Upcoming Catalysts:**")
        for evt in events[:8]:
            if isinstance(evt, dict):
                title = evt.get('title', evt.get('summary', ''))[:150]
                edate = evt.get('event_date', '')
                score = evt.get('score', '')
                cat = evt.get('category', '')
                line = f"- {title}"
                meta = [x for x in [edate, cat, f"score={score}" if score else ''] if x]
                if meta:
                    line += f" ({', '.join(meta)})"
                lines.append(line)
            else:
                lines.append(f"- {str(evt)[:150]}")

    return "\n".join(lines) if lines else str(data)


def _format_debate_history(data: dict) -> str:
    """Format bull/bear debate output."""
    rounds = data.get('debate_rounds', 0)
    lines = [f"**Debate Rounds:** {rounds}"]

    bull_history = data.get('bull_history', [])
    bear_history = data.get('bear_history', [])

    for i in range(max(len(bull_history), len(bear_history))):
        lines.append(f"\n---\n**Round {i + 1}**")
        if i < len(bull_history):
            lines.append(f"\n**Bull:** {bull_history[i]}")
        if i < len(bear_history):
            lines.append(f"\n**Bear:** {bear_history[i]}")

    return "\n".join(lines)


def _format_risk_debate(data: dict) -> str:
    """Format risk debate output."""
    rounds = data.get('debate_rounds', 0)
    lines = [f"**Risk Debate Rounds:** {rounds}"]

    for view in ['aggressive_history', 'conservative_history', 'neutral_history']:
        history = data.get(view, [])
        label = view.replace('_history', '').title()
        if history:
            lines.append(f"\n**{label} View:** {history[-1]}")

    return "\n".join(lines)


def _format_nested_item(item: dict) -> str:
    """Format a nested dict item (e.g., a news article or event)."""
    title = item.get('title', item.get('summary', item.get('ticker', '')))
    company = item.get('company', '')
    score = item.get('score', '')
    category = item.get('category', '')

    parts = []
    if title:
        parts.append(f"**{title}**")
    if company:
        parts.append(f"*{company}*")
    meta = []
    if score:
        meta.append(f"Score: {score}")
    if category:
        meta.append(category)
    if meta:
        parts.append(f"({', '.join(meta)})")
    if item.get('summary') and item.get('summary') != title:
        parts.append(f"\n{item['summary'][:200]}")

    return " ".join(parts) if parts else str(item)[:200]
def md_to_html(text):
    """Convert markdown content to clean HTML for PDF rendering."""
    if not text:
        return ""
    text = text.strip()
    html = markdown.markdown(text, extensions=['tables', 'nl2br'])
    return html


jinja_env.filters['md'] = md_to_html

def fmt_ts(ts):
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(ts)


def load_cycle_data(cur, cycle_id):
    cur.execute(
        """SELECT pc.cycle_id, pc.agent, pc.symbol, pc.started_at, pc.completed_at, pc.status,
                  pc.final_rating, pc.llm_backend, pc.thread_id, pc.origin_source,
                  sn.company_name
           FROM pipeline_cycles pc
           LEFT JOIN symbol_names sn ON pc.symbol = sn.symbol
           WHERE pc.cycle_id = %s""",
        (cycle_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    cycle = {}
    for c, v in zip(cols, row):
        cycle[c] = fmt_ts(v) if isinstance(v, datetime) else v

    cur.execute(
        """SELECT stage, sub_stage, status, completed_at, output_summary, output_full, llm_model
           FROM cycle_stages WHERE cycle_id = %s ORDER BY completed_at NULLS LAST, started_at""",
        (cycle_id,),
    )
    stages = []
    for r in cur.fetchall():
        stage_name = r[0] or ""
        sub_stage = r[1] or stage_name
        content = flatten_content(r[5]) if r[5] else (r[4] or "")
        label, speaker, css = get_speaker(sub_stage)
        stages.append({
            "stage": stage_name, "sub_stage": sub_stage,
            "label": label, "speaker": speaker, "css_class": css,
            "content": content, "time": fmt_ts(r[3]),
        })

    cur.execute(
        """SELECT debate_type, round_number, speaker_role, content, ts
           FROM debate_rounds WHERE cycle_id = %s
           ORDER BY debate_type, round_number""",
        (cycle_id,),
    )
    debate_rounds = []
    for r in cur.fetchall():
        label, speaker, css = get_speaker(r[2])
        debate_rounds.append({
            "debate_type": r[0], "round": r[1],
            "label": label, "speaker": speaker, "css_class": css,
            "content": r[3] or "", "time": fmt_ts(r[4]),
        })

    debate_rounds_grouped = []
    for dr in debate_rounds:
        key = (dr["debate_type"], dr["round"])
        type_label = "Bull-Bear Debate" if dr["debate_type"] == "bull_bear" else "Risk Debate"
        found = False
        for g in debate_rounds_grouped:
            if g["type"] == dr["debate_type"] and g["round"] == dr["round"]:
                g["messages"].append(dr)
                found = True
                break
        if not found:
            debate_rounds_grouped.append({
                "type": dr["debate_type"], "round": dr["round"],
                "type_label": type_label,
                "messages": [dr],
            })

    cur.execute(
        """SELECT rating, direction, conviction, executive_summary,
                  investment_thesis, risk_notes
           FROM cycle_decisions WHERE cycle_id = %s""",
        (cycle_id,),
    )
    dec_row = cur.fetchone()
    decision = None
    if dec_row:
        decision = dict(zip([d[0] for d in cur.description], dec_row))

    analysts = [s for s in stages if "analyst" in s["sub_stage"].lower()]
    other_stages = [s for s in stages if "analyst" not in s["sub_stage"].lower()]

    return {
        "cycle": cycle, "stages": stages, "analysts": analysts,
        "other_stages": other_stages, "debate_rounds": debate_rounds,
        "debate_rounds_grouped": debate_rounds_grouped, "decision": decision,
    }


def render_pdf(template_name, context, output_name):
    template = jinja_env.get_template(template_name)
    html_content = template.render(**context)
    html_path = REPORT_DIR / f"{output_name}.html"
    pdf_path = REPORT_DIR / f"{output_name}.pdf"
    html_path.write_text(html_content, encoding="utf-8")
    HTML(string=html_content).write_pdf(str(pdf_path))
    return pdf_path


@report_router.get("/cycle/{cycle_id}")
def generate_cycle_report(cycle_id: str):
    try:
        with psycopg.connect(CMV4_DSN) as conn, conn.cursor() as cur:
            data = load_cycle_data(cur, cycle_id)
            if not data:
                raise HTTPException(status_code=404, detail="Cycle not found")

            cycle = data["cycle"]
            output_name = f"cycle-{cycle['agent']}-{cycle['symbol']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            context = {
                "report_type": "cycle",
                "title": f"Pipeline Narrative: {cycle['symbol']}",
                "company_name": cycle.get("company_name") or "",
                "company_name": cycle.get("company_name") or "",
                "subtitle": f"{cycle['agent']} Analysis — {cycle['final_rating'] or 'In Progress'}",
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                **data,
            }
            pdf_path = render_pdf("narrative_report.html", context, output_name)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(str(pdf_path), media_type="application/pdf",
                        filename=f"{output_name}.pdf")


@report_router.get("/coverage")
def generate_coverage_report():
    try:
        with psycopg.connect(CMV4_DSN) as conn, conn.cursor() as cur:
            agents = ["Alpha", "Bravo", "Charlie"]
            agent_stats = []

            for agent in agents:
                cur.execute(
                    """SELECT COUNT(*) FILTER (WHERE priority='HIGH'),
                              COUNT(*) FILTER (WHERE priority='MEDIUM'),
                              COUNT(*) FILTER (WHERE priority='LOW'),
                              COUNT(*)
                       FROM agent_watchlist WHERE LOWER(agent) = LOWER(%s) AND removal_date IS NULL""",
                    (agent,),
                )
                r = cur.fetchone()
                cur.execute(
                    "SELECT COUNT(*) FROM pipeline_cycles WHERE agent = %s AND started_at > NOW() - INTERVAL '24 hours'",
                    (agent,),
                )
                cycles_24h = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(DISTINCT symbol) FROM pipeline_cycles WHERE agent = %s",
                    (agent,),
                )
                symbols = cur.fetchone()[0]
                agent_stats.append({
                    "agent": agent, "high": r[0], "medium": r[1], "low": r[2], "total": r[3],
                    "cycles_24h": cycles_24h, "symbols_analyzed": symbols,
                })

            cur.execute("SELECT agent, symbol FROM agent_watchlist WHERE removal_date IS NULL")
            agent_symbols = defaultdict(set)
            for r in cur.fetchall():
                agent_symbols[r[0].capitalize()].add(r[1])

            a = agent_symbols.get("Alpha", set())
            b = agent_symbols.get("Bravo", set())
            c = agent_symbols.get("Charlie", set())
            all_sym = a | b | c

            venn = {
                "alpha_only": sorted(a - b - c),
                "bravo_only": sorted(b - a - c),
                "charlie_only": sorted(c - a - b),
                "alpha_bravo": sorted((a & b) - c),
                "alpha_charlie": sorted((a & c) - b),
                "bravo_charlie": sorted((b & c) - a),
                "all_three": sorted(a & b & c),
            }
            triple = sorted(a & b & c)
            dual_only = sorted((a & b) | (a & c) | (b & c) - (a & b & c))

            output_name = f"coverage-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            context = {
                "report_type": "coverage",
                "title": "Fleet Coverage & Watchlist Report",
                "subtitle": "Dynamic Watchlist Protocol — All Orchestrators",
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "agent_stats": agent_stats,
                "total_unique": len(all_sym),
                "triple_count": len(triple),
                "total_entries": sum(s["total"] for s in agent_stats),
                "convergence_triple": triple,
                "convergence_dual": dual_only,
                "venn": venn,
            }
            pdf_path = render_pdf("narrative_report.html", context, output_name)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(str(pdf_path), media_type="application/pdf",
                        filename=f"{output_name}.pdf")


@report_router.get("/case-study/{symbol}")
def generate_case_study(symbol: str):
    symbol = symbol.upper()
    try:
        with psycopg.connect(CMV4_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT pc.cycle_id, pc.agent, pc.symbol, pc.started_at, pc.completed_at,
                          pc.status, pc.final_rating, pc.llm_backend, pc.thread_id,
                          sn.company_name
                   FROM pipeline_cycles pc
                   LEFT JOIN symbol_names sn ON pc.symbol = sn.symbol
                   WHERE UPPER(pc.symbol) = %s AND pc.status = 'complete'
                   ORDER BY pc.completed_at""",
                (symbol,),
            )
            cycles = cur.fetchall()
            if not cycles:
                raise HTTPException(status_code=404, detail=f"No completed cycles for {symbol}")

            cols = [d[0] for d in cur.description]
            cycle_rows = [dict(zip(cols, r)) for r in cycles]

            thread_ids = set()
            for cr in cycle_rows:
                if cr.get("thread_id"):
                    thread_ids.add(cr["thread_id"])

            thread_events = []
            for tid in thread_ids:
                cur.execute(
                    """SELECT tl.thread_id, tl.cycle_id, tl.sequence, tl.relationship,
                              pc.agent, pc.symbol, pc.started_at, pc.completed_at,
                              pc.status, pc.final_rating
                       FROM thread_links tl
                       JOIN pipeline_cycles pc ON tl.cycle_id = pc.cycle_id
                       WHERE tl.thread_id = %s ORDER BY tl.sequence""",
                    (tid,),
                )
                for r in cur.fetchall():
                    thread_events.append({
                        "sequence": r[2], "relationship": r[3], "agent": r[4],
                        "symbol": r[5], "started_at": fmt_ts(r[6]),
                        "completed_at": fmt_ts(r[7]), "rating": r[9],
                    })

            cycle_details = []
            for cr in cycle_rows:
                cd = load_cycle_data(cur, cr["cycle_id"])
                if cd:
                    cd_entry = {
                        "cycle_id": cr["cycle_id"], "agent": cr["agent"],
                        "symbol": cr["symbol"],
                        "final_rating": cr["final_rating"] or "—",
                        "completed_at": fmt_ts(cr["completed_at"]),
                        "stages": cd["other_stages"][:8],
                    }
                    cycle_details.append(cd_entry)

            agents_involved = list(set(cr["agent"] for cr in cycle_rows))
            comparison = None
            if len(agents_involved) >= 2:
                comp_rows = []
                comp_rows.append({
                    "label": "Rating",
                    "values": [next((cr["final_rating"] or "—" for cr in cycle_rows if cr["agent"] == a), "—") for a in agents_involved],
                })
                comp_rows.append({
                    "label": "LLM Backend",
                    "values": [next((cr.get("llm_backend", "—") for cr in cycle_rows if cr["agent"] == a), "—") for a in agents_involved],
                })
                ratings = [next((cr["final_rating"] for cr in cycle_rows if cr["agent"] == a), None) for a in agents_involved]
                if len(set(r for r in ratings if r)) > 1:
                    divergence = f"Agents diverge on {symbol}: {', '.join(f'{a}={r}' for a, r in zip(agents_involved, ratings) if r)}"
                else:
                    divergence = f"All agents converge on {ratings[0] if ratings[0] else 'pending'} for {symbol}."

                comparison = {
                    "agents": agents_involved,
                    "rows": comp_rows,
                    "divergence_summary": divergence,
                }

            first_cycle = cycle_rows[0]
            origin_narrative = (
                f"{cycle_rows[0].get('company_name') or symbol} ({symbol}) first entered the pipeline on {fmt_ts(first_cycle['started_at'])} "
                f"via {first_cycle['agent']}. "
                f"A total of {len(cycle_rows)} analysis cycles have been completed across "
                f"{len(agents_involved)} orchestrator(s): {', '.join(agents_involved)}."
            )

            output_name = f"case-study-{symbol}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            context = {
                "report_type": "case_study",
                "title": f"Case Study: {symbol}",
                "company_name": cycle_rows[0].get("company_name") or "",
                "company_name": cycle_rows[0].get("company_name") or "",
                "subtitle": f"Multi-Agent Investment Analysis — {len(cycle_rows)} Cycles",
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "origin_narrative": origin_narrative,
                "thread_events": thread_events,
                "cycle_details": cycle_details,
                "comparison": comparison,
            }
            pdf_path = render_pdf("narrative_report.html", context, output_name)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(str(pdf_path), media_type="application/pdf",
                        filename=f"{output_name}.pdf")


@report_router.get("/thesis-tracker")
def thesis_tracker():
    try:
        with psycopg.connect(CMV4_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT symbol, COUNT(*) as cycle_count,
                          COUNT(DISTINCT agent) as agent_count,
                          ARRAY_AGG(DISTINCT agent) as agents,
                          ARRAY_AGG(DISTINCT final_rating) FILTER (WHERE final_rating IS NOT NULL) as ratings,
                          MIN(started_at) as first_analyzed,
                          MAX(completed_at) as last_analyzed
                   FROM pipeline_cycles
                   WHERE status = 'complete'
                   GROUP BY symbol
                   HAVING COUNT(*) >= 2
                   ORDER BY COUNT(*) DESC, symbol"""
            )
            rows = cur.fetchall()
            tracker = []
            for r in rows:
                ratings = r[4] or []
                consensus = len(set(ratings)) == 1
                tracker.append({
                    "symbol": r[0], "cycle_count": r[1], "agent_count": r[2],
                    "agents": r[3], "ratings": ratings,
                    "consensus": consensus,
                    "consensus_rating": ratings[0] if consensus and ratings else None,
                    "first_analyzed": fmt_ts(r[5]), "last_analyzed": fmt_ts(r[6]),
                })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"tracker": tracker, "timestamp": datetime.now(timezone.utc).isoformat()}


@report_router.get("/orchestrator-comparison/{symbol}")
def orchestrator_comparison(symbol: str):
    symbol = symbol.upper()
    try:
        with psycopg.connect(CMV4_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT pc.cycle_id, pc.agent, pc.symbol, pc.final_rating,
                          pc.started_at, pc.completed_at, pc.llm_backend,
                          cd.rating, cd.direction, cd.conviction,
                          cd.executive_summary, cd.investment_thesis, cd.risk_notes
                   FROM pipeline_cycles pc
                   LEFT JOIN cycle_decisions cd ON pc.cycle_id = cd.cycle_id
                   WHERE UPPER(pc.symbol) = %s AND pc.status = 'complete'
                   ORDER BY pc.agent, pc.completed_at DESC""",
                (symbol,),
            )
            rows = cur.fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail=f"No data for {symbol}")

            cols = [d[0] for d in cur.description]
            agents = {}
            for r in rows:
                entry = dict(zip(cols, r))
                for k, v in entry.items():
                    if isinstance(v, datetime):
                        entry[k] = fmt_ts(v)
                agent = entry["agent"]
                if agent not in agents:
                    agents[agent] = []
                agents[agent].append(entry)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"symbol": symbol, "by_agent": agents, "timestamp": datetime.now(timezone.utc).isoformat()}
