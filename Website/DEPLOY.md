# Deploy the evidence site to Cloudflare Pages

The site is fully static. You upload the `Website/dist/` folder, and nothing else.

Everything except the login page and the code libraries is encrypted with your password, so Cloudflare only stores scrambled files.

## 1. Build with your real password (on this laptop)

Pick a **long** password: 4 or more random words, e.g. `copper-violet-tram-ocean`. Anyone who gets a copy of `dist/` can try guesses offline, so a short password is weak. The password is never saved in plain text anywhere.

```powershell
cd C:\Users\hp\Desktop\qidk\Website
$env:SITE_PASSWORD = "your-long-password-here"
py -3 build\build.py            # collects the data, then builds; add --no-collect to skip collecting
Remove-Item Env:SITE_PASSWORD   # forget it in this shell
```

When the build succeeds:
- it prints a summary;
- `dist/` contains `index.html`, `auth.json`, `_headers`, `css/`, `js/`, `vendor/`, and only `*.enc` files under `data/` and `pages/`;
- the build has already checked that your password string does not appear anywhere in `dist/`.

Optional local check before you upload:

```powershell
py -3 -m http.server 8080 -d dist
# open http://127.0.0.1:8080 and unlock with your password
```

## 2. Upload to Cloudflare Pages

### Option A: dashboard (no tools needed)

1. Go to https://dash.cloudflare.com and choose **Workers & Pages**, then **Create**, then **Pages**, then **Upload assets**.
2. Name the project (e.g. `qidk-edge-ai`) and choose **Create project**.
3. **Drag the whole `Website/dist` folder** into the upload box, then choose **Deploy site**.
4. The site appears at `https://<project>.pages.dev`.

To update the site later: open the project, choose **Create deployment**, and drag `dist/` again.

### Option B: command line (Wrangler)

```powershell
npx wrangler login                                   # once; opens the browser
npx wrangler pages deploy dist --project-name qidk-edge-ai
```

## 3. After deploying, check

- Open the `pages.dev` URL. You should see the password screen.
- A wrong password is rejected; the right one opens the Deck page.
- Opening `https://<project>.pages.dev/data/catalog.json.enc` shows unreadable bytes. That is correct.
- Drop the PPT exported as PDF on the Deck page. PDF is exact; `.pptx` is best effort. It stays in the browser only.

## 4. Optional extras

- **Custom domain:** in the project, open **Custom domains** and add yours; Cloudflare creates the DNS records.
- **Second lock:** in **Zero Trust → Access → Applications**, add the `pages.dev` host to allow only listed emails. This is free for up to 50 users. It sits in front of the password, so your password protection stays as it is.

## 5. Rebuild when numbers change

When training finishes or new proofs arrive, run step 1 again; the collectors re-read `proofs/`, the HANDBOOK and the training log. Then upload `dist/` again (step 2).

The raw-data explorer needs its own collector, which takes about 3 min and is not run automatically:

```powershell
py -3 build\collect\rawdata.py
```

## Notes

- `_headers` sets a strict Content Security Policy and caching. Don't remove it.
- Never upload `Website/data/` (plain, private) or anything outside `dist/`.
- Changing the password means building again with the new one, then uploading again. Old links still work, but the old password stops working.
