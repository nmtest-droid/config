# Единственный демонстрационный сценарий эмулятора.
# Команды выполняются внутри виртуальной файловой системы.

pwd
ls
ls -l

# Навигация и чтение файлов
cd docs
pwd
ls
cat readme.txt

# Фильтрация повторяющихся строк
uniq repeated.txt
uniq -c repeated.txt
uniq -d repeated.txt
uniq -u repeated.txt

# Подсчёт размера файлов и каталогов
du .
du -ah .
du -sh .

# Создание файла и изменение владельца/группы
touch report.txt
ls -l
chown student:developers report.txt
chown -R teamlead:projects projects
ls -l
cd ..

# Проверка изменений в корневом каталоге
ls -l
cat hello.txt
exit
