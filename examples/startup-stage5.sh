# Этап 5: touch и chown; все изменения выполняются только в памяти VFS
pwd
ls
ls -l

# touch: создание одного и нескольких пустых файлов
touch stage5-new.txt
touch docs/stage5-note.txt docs/stage5-empty.txt
ls -l
cat stage5-new.txt

# touch: существующий файл, режим без создания, абсолютный и относительный пути
touch hello.txt
touch -c not-created.txt
touch /docs/stage5-absolute.txt
ls -l docs

# touch: ошибки параметров и путей
touch
touch -z invalid.txt
touch missing-dir/file.txt
touch docs/guide.txt/child.txt

# chown: только владелец, только группа, владелец и группа
chown alice stage5-new.txt
chown :students stage5-new.txt
chown bob:developers docs/stage5-note.txt
ls -l

# chown: рекурсивная смена владельца/группы для каталога и содержимого
chown -R teamlead:project docs
ls -l docs

# chown: абсолютный путь, ошибки синтаксиса и отсутствующий объект
chown root:wheel /hello.txt
chown
chown : stage5-new.txt
chown a:b:c stage5-new.txt
chown -z alice stage5-new.txt
chown alice absent.txt

# Продолжение после ошибок и завершение
pwd
exit
