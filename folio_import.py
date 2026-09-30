"""Upload a .mrc file to FOLIO Data Import and run a job profile on it (instruction
step 23), then report the job status, log entries and the purchase orders created.

A preflight check (folio_preflight.py) runs first and stops the load on any error.
Without --live it stops after the preflight.
"""
import argparse
import time
from pathlib import Path

import httpx
from pymarc import MARCReader

from ebsconet_prep import load_config
from folio_common import connect
from folio_preflight import route_from_profile, run_preflight

DONE = {"COMMITTED", "ERROR", "CANCELLED", "DISCARDED"}


def po_numbers(mrc_path):
    with open(mrc_path, "rb") as fh:
        recs = list(MARCReader(fh, to_unicode=True, force_utf8=True))
    return [{s.code: s.value for s in r["990"].subfields}["o"] for r in recs]


def upload_and_run(client, mrc_path, job_profile_id, job_profile_name, wait=180):
    base = client.gateway_url.rstrip("/")
    # drop the default JSON content-type; the upload sets its own
    headers = {k: v for k, v in client.folio_headers.items()
               if k.lower() != "content-type"}
    name = Path(mrc_path).name
    with httpx.Client(timeout=60) as http:
        definition = http.post(
            base + "/data-import/uploadDefinitions", headers=headers,
            json={"fileDefinitions": [{"name": name}]}).raise_for_status().json()
        def_id = definition["id"]
        file_id = definition["fileDefinitions"][0]["id"]
        data = Path(mrc_path).read_bytes()
        file_url = "%s/data-import/uploadDefinitions/%s/files/%s" % (base, def_id, file_id)
        if client.folio_get("/data-import/splitStatus").get("splitStatus"):
            # S3-backed upload: presigned PUT, then ask FOLIO to assemble the file
            slot = client.folio_get("/data-import/uploadUrl",
                                    query_params={"filename": name})
            put = http.put(slot["url"], content=data)      # no FOLIO headers on S3
            put.raise_for_status()
            http.post(file_url + "/assembleStorageFile", headers=headers,
                      json={"uploadId": slot["uploadId"], "key": slot["key"],
                            "tags": [put.headers["ETag"]]}).raise_for_status()
        else:
            up = dict(headers, **{"Content-Type": "application/octet-stream"})
            http.post(file_url, headers=up, content=data).raise_for_status()
        definition = http.get("%s/data-import/uploadDefinitions/%s" % (base, def_id),
                              headers=headers).raise_for_status().json()
        http.post("%s/data-import/uploadDefinitions/%s/processFiles?defaultMapping=false"
                  % (base, def_id), headers=headers,
                  json={"uploadDefinition": definition,
                        "jobProfileInfo": {"id": job_profile_id,
                                           "name": job_profile_name,
                                           "dataType": "MARC"}}).raise_for_status()
    return wait_for_jobs(client, name, definition["createDate"], wait)


def select_jobs(jobs, since):
    """Jobs started at or after `since`, oldest first. Ignores earlier uploads of a
    file with the same name."""
    return sorted((j for j in jobs if j.get("startedDate", "") >= since),
                  key=lambda j: j["hrId"])


def jobs_finished(jobs):
    """True when the import has run to the end. A split file gives one composite
    parent plus child jobs (the plain 'parent single' job stays FILE_UPLOADED);
    an unsplit file gives just the single job."""
    split = [j for j in jobs if j.get("subordinationType", "").startswith("COMPOSITE")]
    check = split or [j for j in jobs if j.get("subordinationType") == "PARENT_SINGLE"]
    return bool(check) and all(j.get("status") in DONE for j in check) and (
        not split or any(j["subordinationType"] == "COMPOSITE_CHILD" for j in split))


def wait_for_jobs(client, file_name, since, wait=180):
    """Wait for the jobs started by this upload; return them oldest first."""
    stem = Path(file_name).stem
    jobs = []
    for _ in range(wait // 3):
        found = client.folio_get("/metadata-provider/jobExecutions", query_params={
            "fileNamePattern": stem, "limit": 50,
            "sortBy": "started_date,desc"}).get("jobExecutions", [])
        jobs = select_jobs(found, since)
        if jobs_finished(jobs):
            return jobs
        time.sleep(3)
    raise SystemExit("timed out waiting for import jobs; last seen: %s" % [
        (j["hrId"], j.get("subordinationType"), j.get("status")) for j in jobs])


def job_log(client, job_id):
    r = client.folio_get("/metadata-provider/jobLogEntries/%s" % job_id,
                         query_params={"limit": 50})
    return r.get("entries", [])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mrc")
    p.add_argument("--ini", required=True)
    p.add_argument("--job-profile", required=True, help="job profile NAME")
    p.add_argument("--live", action="store_true")
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--route", choices=("online", "print", "pe"),
                   help="needed only if the job profile name is not the standard one")
    p.add_argument("--skip-preflight", action="store_true",
                   help="load even if the preflight check finds errors")
    args = p.parse_args(argv)
    client = connect(args.ini)
    cfg = load_config(args.config)
    numbers = po_numbers(args.mrc)
    route = args.route or route_from_profile(args.job_profile, cfg)
    if route is None:
        raise SystemExit("cannot tell the route from job profile %r; use --route"
                         % args.job_profile)
    ok = run_preflight(client, args.mrc, route, cfg, args.job_profile)
    if not ok and not args.skip_preflight:
        raise SystemExit("preflight found errors; nothing was loaded "
                         "(--skip-preflight to load anyway)")
    profiles = client.folio_get("/data-import-profiles/jobProfiles", key="jobProfiles",
                                query_params={"query": 'name=="%s"' % args.job_profile})
    if len(profiles) != 1:
        raise SystemExit("job profile %r: %d matches" % (args.job_profile, len(profiles)))
    if not args.live:
        print("dry run: preflight only; would run job profile", profiles[0]["id"])
        return 0
    jobs = upload_and_run(client, args.mrc, profiles[0]["id"], args.job_profile)
    for job in jobs:
        print("job HRID %s %s %s progress %s" % (
            job["hrId"], job.get("subordinationType"), job.get("status"),
            (job.get("progress") or {}).get("current")))
        for e in job_log(client, job["id"]):
            info = e.get("relatedPoLineInfo") or {}
            print("   record %s %-45s %s %s" % (
                e.get("sourceRecordOrder"), (e.get("sourceRecordTitle") or "")[:45],
                info.get("actionStatus", ""), info.get("error") or e.get("error") or ""))
    for n in numbers:
        po = client.folio_get("/orders/composite-orders", key="purchaseOrders",
                              query_params={"query": 'poNumber=="%s"' % n})
        print("PO", n, "->", [(o["id"], o["workflowStatus"]) for o in po] or "NOT CREATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
