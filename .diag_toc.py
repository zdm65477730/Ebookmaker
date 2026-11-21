from collections import Counter
from ebookmaker.config import load_config
from ebookmaker.cli import _make_limiter, _wire_runtime
from ebookmaker.auto import load_learned_site, auto_dir_for
from ebookmaker.sites.base import (collect_series_pages, normalize_toc,
                                   _title_number, _href_number)

cfg = load_config("config.yaml")
url = "https://www.bqg2.org/html/58/58180/"
site = load_learned_site(auto_dir_for(cfg.workdir, cfg.auto.save_dir), url)
limiter = _make_limiter(cfg)
proxy, http = _wire_runtime(cfg, limiter)
html = http.get(url).text
entries = list(site.parse_toc(html, url))
pages = collect_series_pages(html, url, lambda pu: http.get(pu, referer=url).text)
print("分页页数:", len(pages) + 1)
for pu, ph in pages:
    entries.extend(site.parse_toc(ph, url))
print("合并:", len(entries))
norm = normalize_toc(entries)
print("规范化:", len(norm))

hrefs = [e.href for e in norm]
print("规范化后 href 重复:", [h for h, c in Counter(hrefs).items() if c > 1][:5])
kept = set(hrefs)
lost = [e for e in entries if e.href not in kept]
print("被丢弃条目:", len(lost))
for e in lost[:20]:
    print("  丢:", repr(e.href), repr(e.title[:44]),
          "tnum=", _title_number(e.title), "unum=", _href_number(e.href))

# 标题序号连续性
tns = sorted(_title_number(e.title) for e in norm if _title_number(e.title) is not None)
print("标题序号范围:", tns[0], "-", tns[-1], "有序号章数:", len(tns))
missed = sorted(set(range(tns[0], tns[-1] + 1)) - set(tns))
print("标题序号缺号:", missed[:20])
