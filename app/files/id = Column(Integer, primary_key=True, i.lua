id = Column(Integer, primary_key=True, index=True)
file_id = Column(Integer, ForeignKey("files.id"))
action = Column(String, nullable=False)  
user_id = Column(Integer, ForeignKey("users.id"))
timestamp = Column(DateTime(timezone=True), default=datetime.now())

file = relationship("FileModel", back_populates="logs")
user = relationship("User")

Scenario 1:
    


Scenario 2:
-> File/Folder Foreground UI Create

    -> File/Folder Background Create ( No Logs )

        -> Action : File/Folder Download 

            id=1,path="uploads\naitik\rohit",action="PRE-CREATED","user_id"="system",timestamp="system creation time"
            id=2,path="uploads\naitik\rohit",action="download","user_id"="naitik",timestamp="current_time"

    -> Create From Frontend
        id=1,path="uploads\naitik\rohit",action="CREATED","user_id"="system",timestamp="system creation time",app_note=""

    -> Move From Frontend
        id=1,path="uploads\naitik\rohit",action="MOVED","user_id"="naitik",timestamp="system creation time",app_note="moved touploads\naitik2\rohit"
        id=2,path="uploads\naitik2\rohit",action="CREATED","user_id"="naitik",timestamp,app_note="moved from uploads\naitik\rohit"

    -> Copied From Frontend
        id=1,path="uploads\naitik\rohit",action="COPIED","user_id"="naitik",timestamp="system creation time",app_note_frontend="",app_note="COPIED to uploads\naitik2\rohit"
        id=2,path="uploads\naitik2\rohit",action="CREATED","user_id"="naitik",timestamp,app_note="COPIED from uploads\naitik\rohit"

    -> Deleted From Frontend
        id=1,path="uploads\naitik\rohit\sneha\sneha.txt",action="DELETED","user_id"="naitik",timestamp="system creation time",app_note_frontend="DELETED By : <user>",app_note="DELETED to uploads\naitik\rohit\sneha\sneha.txt"
        
        TBL_DELETED
        id=1,path="uploads\naitik\rohit\sneha\sneha.txt",user_id="naitik",timestamp="deleted time"

        -> When Recovered
            - Check File Exist -> if exist show warning to overwrite or merge
            - Remove From TBL_DELETED
            - Add Entry To Destination Folder
                id=1,path="uploads\naitik\rohit\sneha\sneha.txt",action="RECOVERED","user_id"="naitik(admin)",timestamp="recovered time",app_note_frontend="Recovered By : <user>",app_note="Recovered to uploads\naitik\rohit\sneha\sneha.txt"

    -> Rename


