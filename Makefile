do-drysync:
	rsync -anzP \
	--exclude='*.pyc' \
	--exclude='__pycache__' \
	--exclude='.DS_Store' \
	--delete \
	scaffolds/ $(TARGET):/home/ubuntu/scaffolds/

do-sync:
	rsync -azP \
	--exclude='*.pyc' \
	--exclude='__pycache__' \
	--exclude='.DS_Store' \
	scaffolds/ $(TARGET):/home/ubuntu/scaffolds/
