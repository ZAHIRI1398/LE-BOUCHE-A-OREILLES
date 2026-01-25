# Nombre de workers = (2 x nombre de cœurs) + 1
workers = 2
# Utilisez des threads si nécessaire (pour les applications I/O bound)
threads = 4
# Adresse et port d'écoute
bind = '0.0.0.0:10000'
# Délai d'attente (en secondes)
timeout = 120
# Journalisation
accesslog = '-'
errorlog = '-'
# Rediriger stdout/stderr vers le log d'erreur
capture_output = True
# Redémarrer les workers qui prennent trop de temps
max_requests = 1000
max_requests_jitter = 50