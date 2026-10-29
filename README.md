# Formulaire de contribution – Agenda

Page `index.html` (formulaire, éditeur de texte intégré sans dépendance) + fonction Python `api/submit.py` qui envoie chaque proposition par e-mail, avec la fiche en texte dans le corps et en JSON en pièce jointe (prête pour l'import dans Drupal).

## Mise en ligne

1. Pousser ce dossier sur un dépôt GitHub.
2. Sur Vercel : **Add New > Project**, importer le dépôt, aucun réglage de build (Framework : *Other*).
3. Dans **Settings > Environment Variables**, ajouter :

| Variable | Valeur |
|---|---|
| `SMTP_USER` | `tphilipponneau@gmail.com` |
| `SMTP_PASSWORD` | un **mot de passe d'application** Gmail |
| `MAIL_TO` | `tphilipponneau@gmail.com` (facultatif, c'est la valeur par défaut) |

4. Redéployer (Deployments > ⋯ > Redeploy) pour que les variables soient prises en compte.

### Créer le mot de passe d'application Gmail

La validation en deux étapes doit être activée sur le compte Google. Ensuite : <https://myaccount.google.com/apppasswords> → créer un mot de passe « Vercel agenda » → copier les 16 caractères (sans espaces) dans `SMTP_PASSWORD`.

## Test en local

```bash
npm i -g vercel
vercel dev
```

## Protection

- Pot de miel anti-robots (champ caché `website`).
- Toutes les valeurs sont revalidées et tronquées côté serveur.
- Le texte de présentation (HTML) est nettoyé côté serveur : seules les balises p, br, strong, em, u, s, h2, h3, listes et liens http(s) sont conservées.
- La page est en `noindex`.
