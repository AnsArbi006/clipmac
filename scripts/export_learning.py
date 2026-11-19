"""Export collection-only evidence. --refresh reads YouTube; never edits/uploads."""
import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clipmac.state import Store, RUNTIME, atomic_json, settings
from clipmac.learning import learning_export, collect_performance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    store = Store()
    if args.refresh:
        from clipmac import publisher
        cfg = settings()
        service = publisher.service_for_channel(cfg['channel_id'])
        collect_performance(store, service, cfg['channel_id'], time.time(), force=True)
    for job in store.rows():
        store.capture_learning_context(job)
    data = learning_export(store)
    data['exported_at'] = time.time()
    folder = RUNTIME / 'learning'
    atomic_json(folder / 'dataset.json', data)
    latest = {}
    for sample in data['performance_samples']:
        latest[sample['clip_id']] = sample
    jobs = {j['id']: j for j in store.rows()}
    metadata = {m['sample_id']: m['metadata'] for m in data['youtube_metadata_observations']}
    fields = ['clip_id', 'youtube_id', 'title', 'description', 'observed_at', 'age_seconds',
              'views', 'likes', 'comments', 'likes_per_100_views', 'comments_per_100_views']
    with (folder / 'latest-ratios.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for clip_id, sample in latest.items():
            presentation = metadata.get(sample['id'], jobs[clip_id]['result'].get('metadata', {}))
            writer.writerow({**{k: sample[k] for k in fields if k in sample},
                'title': presentation.get('title'), 'description': presentation.get('description'),
                **{k: sample['ratios'][k] for k in ('likes_per_100_views', 'comments_per_100_views')}})
    print(f"{len(latest)} Videos, {len(data['performance_samples'])} Messungen, "
          f"{len(data['video_contexts'])} lokale Schnittfassungen. Phase: Datensammlung.")
    print(folder / 'dataset.json')
    print(folder / 'latest-ratios.csv')


if __name__ == '__main__':
    main()
