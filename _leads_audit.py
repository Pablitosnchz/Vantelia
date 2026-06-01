import sqlite3
db = sqlite3.connect('/app/storage/outreach/outreach.db')
c = db.cursor()

print('=== REPLIED ===')
for r in c.execute("select p.email,p.business_name,p.niche,p.city,p.website,p.notes,(select s.stage from sends s where s.email=p.email and s.mode='send' order by s.sent_at desc limit 1) from prospects p where p.status='replied'"):
    print(r)

print()
print('=== EVENTS reply/reply_intent ===')
cols_e = [d[0] for d in c.execute("PRAGMA table_info(events)").fetchall()]
print('event cols:', cols_e)
for r in c.execute("select * from events where type in ('reply','reply_intent') order by rowid desc limit 15"):
    print(dict(zip(cols_e, r)))

print()
print('=== HOT (opens+clicks, not replied) ===')
for r in c.execute("select p.email,p.business_name,p.niche,p.city,p.website,sum(case when e.type='open' then 1 else 0 end),sum(case when e.type='click' then 1 else 0 end) from prospects p join events e on e.email=p.email where p.status not in ('replied','client','lost','baja') and e.type in ('open','click') group by p.email having sum(case when e.type='open' then 1 else 0 end)+sum(case when e.type='click' then 1 else 0 end)*3>=2 order by sum(case when e.type='click' then 1 else 0 end)*3+sum(case when e.type='open' then 1 else 0 end) desc limit 10"):
    print(r)
