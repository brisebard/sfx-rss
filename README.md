# Satellifacts RSS (non officiel)

Génère un flux RSS enrichi (titre complet, description, date, image) à partir
de `https://www.satellifacts.com/api/news-feed`, en allant chercher les
métadonnées Open Graph de chaque nouvel article.

## Mise en place

1. Créez un nouveau repo GitHub (public, pour des minutes Actions illimitées)
   et poussez-y ces fichiers.
2. Dans **Settings → Pages**, activez GitHub Pages sur la branche `main`,
   dossier `/docs`.
3. Dans **Settings → Actions → General → Workflow permissions**, sélectionnez
   **Read and write permissions** (nécessaire pour que le workflow puisse
   committer le fichier `feed.xml` mis à jour).
4. Le workflow `.github/workflows/update-feed.yml` tourne toutes les
   5 minutes (minimum pratique de GitHub Actions) et peut aussi être
   déclenché manuellement depuis l'onglet **Actions**.
5. Une fois la première exécution passée, le flux est disponible à :
   `https://<votre-compte>.github.io/<nom-du-repo>/feed.xml`

## Fonctionnement

- `generate_feed.py` télécharge `/api/news-feed`, repère les nouveaux liens
  d'articles (absents de `data/articles.json`), et va chercher sur chaque
  page : `og:title`, `og:description`/`description`, `article:published_time`,
  `og:image`.
- Les articles déjà vus ne sont **pas** re-téléchargés (cache dans
  `data/articles.json`), pour rester léger et respectueux du site source.
- Le flux ne conserve que les 100 articles les plus récents.

## Limites à connaître

- GitHub n'exécute pas les workflows planifiés à la minute exacte : des
  retards de quelques minutes sont normaux, en particulier aux heures de
  forte charge.
- Un workflow planifié est automatiquement désactivé après 60 jours sans
  activité sur le dépôt. Comme ce projet committe à chaque nouvel article,
  ça ne devrait pas arriver tant que le site est actif.
- Certains articles Satellifacts sont réservés aux abonnés : le script
  n'essaie pas de contourner ça, il lit uniquement les balises meta déjà
  publiques dans le `<head>` de la page (prévues pour le partage social),
  ce qui donne un titre et un résumé même pour les articles payants.
