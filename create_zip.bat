@echo off
REM Script pour créer un fichier ZIP installable pour l'add-on Blender (Windows)

REM Nom du fichier ZIP de sortie
set ZIP_NAME=dice-maker.zip

REM Supprimer l'ancien ZIP s'il existe
if exist "%ZIP_NAME%" (
    del "%ZIP_NAME%"
    echo Ancien fichier ZIP supprimé
)

REM Vérifier que les fichiers nécessaires existent
if not exist "__init__.py" (
    echo Erreur: Fichier __init__.py introuvable
    echo Assurez-vous d'être dans le bon répertoire.
    pause
    exit /b 1
)

REM Créer le ZIP avec PowerShell (Windows 10+)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$files = @('__init__.py', 'dice_maker_panel.py', 'dice_maker_operator.py', 'dice_maker_svg.py', 'LICENSE'); $existing = $files | Where-Object { Test-Path $_ }; if ($existing.Count -gt 0) { Compress-Archive -Path $existing -DestinationPath '%ZIP_NAME%' -Force; Write-Host '✓ Fichier ZIP créé : %ZIP_NAME%' } else { Write-Host '✗ Erreur : Aucun fichier trouvé'; exit 1 }"

if exist "%ZIP_NAME%" (
    echo.
    echo ✓ Vous pouvez maintenant installer cet add-on dans Blender via:
    echo   Edit ^> Preferences ^> Add-ons ^> Install...
) else (
    echo.
    echo ✗ Erreur: Impossible de créer le fichier ZIP.
    echo Assurez-vous d'avoir PowerShell installé (Windows 10+).
    echo.
    echo Alternative: Utilisez 7-Zip ou WinRAR pour créer manuellement le ZIP
    echo en incluant les fichiers: __init__.py, dice_maker_panel.py, dice_maker_operator.py, dice_maker_svg.py, LICENSE
)

pause

