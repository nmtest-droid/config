# Этап 4: ls, cd, uniq, du; успешные сценарии и ошибки
pwd
ls
ls docs
ls missing
ls docs/guide.txt
cd docs
pwd
ls
cd ..
cd missing
cd hello.txt
cd home/student/projects/demo
pwd
ls
cd /

# uniq: удаление соседних повторов и все режимы вывода
uniq examples.txt
uniq -c examples.txt
uniq -d examples.txt
uniq -u examples.txt
uniq missing.txt
uniq -z examples.txt
uniq -c -d examples.txt
uniq

# du: каталоги, отдельные файлы, рекурсивная детализация и форматирование
 du .
du -a .
du -h .
du -sh docs
du docs/guide.txt
du missing
du -z

du docs extra
exit
