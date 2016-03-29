
from subprocess import Popen, PIPE
from os.path import exists, join

from qiita_db.sql_connection import TRN
from qiita_db.artifact import Artifact
from qiita_db.util import (insert_filepaths, convert_to_id, get_mountpoint,
                           get_mountpoint_path_by_id)


tgz_id = convert_to_id("tgz", "filepath_type")
_, analysis_mp = get_mountpoint('analysis')[0]

with TRN:
    #
    # Generating compressed files for picking failures -- artifact_type = BIOM
    #
    sql = """SELECT artifact_id FROM qiita.artifact
                JOIN qiita.artifact_type USING (artifact_type_id)
                WHERE artifact_type = 'BIOM'"""
    TRN.add(sql)

    for r in TRN.execute_fetchindex():
        to_tgz = None
        a = Artifact(r[0])
        for _, fp, fp_type in a.filepaths:
            if fp_type == 'directory':
                # removing / from the path if it exists
                to_tgz = fp[:-1] if fp[-1] == '/' else fp
                break

        if to_tgz is None:
            continue

        tgz = to_tgz + '.tgz'
        if not exists(tgz):
            cmd = 'tar zcf %s %s' % (tgz, to_tgz)
            proc = Popen(cmd, universal_newlines=True, shell=True, stdout=PIPE,
                         stderr=PIPE)
            stdout, stderr = proc.communicate()
            return_value = proc.returncode
            if return_value != 0:
                raise ValueError(
                    "There was an error:\nstdout:\n%s\n\nstderr:\n%s"
                    % (stdout, stderr))

        a_id = a.id
        # Add the new tgz file to the artifact.
        fp_ids = insert_filepaths([(tgz, tgz_id)], a_id, a.artifact_type,
                                  "filepath")
        sql = """INSERT INTO qiita.artifact_filepath
                    (artifact_id, filepath_id)
                 VALUES (%s, %s)"""
        sql_args = [[a_id, fp_id] for fp_id in fp_ids]
        TRN.add(sql, sql_args, many=True)
        TRN.execute()

    #
    # Generating compressed files for analysis
    #
    TRN.add("SELECT analysis_id FROM qiita.analysis")
    for result in TRN.execute_fetchindex():
        analysis_id = result[0]
        # retrieving all analysis filepaths, we could have used
        # Analysis.all_associated_filepath_ids but we could run into the
        # analysis not belonging to the current portal, thus using SQL

        sql = """SELECT filepath, data_directory_id
                 FROM qiita.filepath
                    JOIN qiita.analysis_filepath USING (filepath_id)
                 WHERE analysis_id = %s"""
        TRN.add(sql, [analysis_id])
        fps = set([tuple(r) for r in TRN.execute_fetchindex()])
        sql = """SELECT filepath, data_directory_id
                 FROM qiita.analysis_job
                    JOIN qiita.job USING (job_id)
                    JOIN qiita.job_results_filepath USING (job_id)
                    JOIN qiita.filepath USING (filepath_id)
                 WHERE analysis_id = %s"""
        TRN.add(sql, [analysis_id])
        fps = fps.union([tuple(r) for r in TRN.execute_fetchindex()])

        # no filepaths in the analysis
        if not fps:
            continue

        tgz = join(analysis_mp, '%d_files.tgz' % analysis_id)
        if not exists(tgz):
            full_fps = [join(get_mountpoint_path_by_id(mid), f)
                        for f, mid in fps]
            cmd = 'tar zcf %s %s' % (tgz, ' '.join(full_fps))
            proc = Popen(cmd, universal_newlines=True, shell=True, stdout=PIPE,
                         stderr=PIPE)
            stdout, stderr = proc.communicate()
            return_value = proc.returncode
            if return_value != 0:
                raise ValueError(
                    "There was an error:\nstdout:\n%s\n\nstderr:\n%s"
                    % (stdout, stderr))

        # Add the new tgz file to the analysis.
        fp_ids = insert_filepaths([(tgz, tgz_id)], analysis_id, 'analysis',
                                  "filepath")
        sql = """INSERT INTO qiita.analysis_filepath
                    (analysis_id, filepath_id)
                 VALUES (%s, %s)"""
        sql_args = [[analysis_id, fp_id] for fp_id in fp_ids]
        TRN.add(sql, sql_args, many=True)
        TRN.execute()
