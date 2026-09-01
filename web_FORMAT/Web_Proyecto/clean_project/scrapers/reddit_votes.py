import asyncio
import asyncpraw
import pandas as pd
from pathlib import Path
# CSV_PATH = "/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/project_web/Web_Proyecto/datos/admin/bikesharing/reddit_global_dataset.csv"
async def test_reddit():
    reddit = asyncpraw.Reddit(
        client_id="TXr9FuPxqBWzt5Se6B7O4w",
        client_secret="FDLxAYCobON7T1yadE-Ip52qtHJRBA",
        user_agent="test"
    )

    post = await reddit.submission(id="1tbf0k9")#1sbaail")  # ID real
    post_url = f"https://www.reddit.com{post.permalink}"
    await post.load()

    author = post.author
    from pprint import pprint

    if author is not None:
        await author.load()

        pprint(author.__dict__)

    if author is not None:
        await author.load()

        print("USUARIO:", author.name)

        print("LINK KARMA:", author.link_karma)
        print("COMMENT KARMA:", author.comment_karma)
        print("TOTAL KARMA A MANO:", author.link_karma + author.comment_karma)
        print("TOTAL KARMA:", author.total_karma)
    else:
        print("Usuario eliminado")

    print("URL:", post_url)
    print("TITLE:", post.title)
    print("SCORE:", post.score)
    print("UPVOTE RATIO:", post.upvote_ratio)

    try:
        eps = 1e-6
        if abs(post.upvote_ratio - 0.5) > eps:
            est_up = None
            est_down = None
        else:
            est_up = int((post.score*post.upvote_ratio) / ((2 * post.upvote_ratio) - 1))
            est_down = est_up - post.score

            print("EST UPVOTES:", est_up)
            print("EST DOWNVOTES:", est_down)

    except:
        print("No se pudo estimar")

asyncio.run(test_reddit())

import asyncio
import pandas as pd
import asyncpraw



async def test_reddit_dataset():

    reddit = asyncpraw.Reddit(
        client_id="TXr9FuPxqBWzt5Se6B7O4w",
        client_secret="FDLxAYCobON7T1yadE-Ip52qtHJRBA",
        user_agent="test"
    )

    df = pd.read_csv(CSV_PATH, sep=";")

    posts = df[df["tipo"] == "POST"]

    print(f"POSTS encontrados: {len(posts)}")

    for idx, row in posts.iterrows():

        try:
            post_id = row["id_raiz"]

            print("\n" + "=" * 80)
            print("POST ID:", post_id)

            post =  await reddit.submission(id=f"{post_id}")
            await post.load()
            post_url = f"https://www.reddit.com{post.permalink}"
            print("URL:", post_url)
            print("TITLE:", post.title)
            print("SCORE:", post.score)
            print("UPVOTE_RATIO:", post.upvote_ratio)
            print("COMMENTS:", post.num_comments)

            # ---------------------------------------------------
            # Estimación upvotes/downvotes
            # ---------------------------------------------------

            ratio = post.upvote_ratio
            score = post.score

            try:
                eps = 1e-6

                if abs((2 * ratio) - 1) < eps:
                    print("⚠️ ratio≈0.5 → no estimable")
                    input("\nENTER para siguiente post...")
                    if score == 0:
                        print("⚠️ score=0 → sin votos")
                        est_up = 0
                        est_down = 0
                        print("EST_UPVOTES:", est_up)
                        print("EST_DOWNVOTES:", est_down)
                        input("\nENTER para siguiente post...")    
                    else: 
                        print("⚠️ score≠0 → votos pero ratio no confiable")
                        est_up = score
                        est_down = score
                        print("EST_UPVOTES:", est_up)
                        print("EST_DOWNVOTES:", est_down)
                        input("\nENTER para siguiente post...")  

                else:
                    est_up = int(
                        (score * ratio) / ((2 * ratio) - 1)
                    )

                    est_down = est_up - score

                    print("EST_UPVOTES:", est_up)
                    print("EST_DOWNVOTES:", est_down)

            except Exception as e:
                print("⚠️ Error estimando votos:", e)
                input("\nENTER para siguiente post...")

        except Exception as e:
            print(f"⚠️ Error cargando post {post_id}: {e}")
            input("\nENTER para siguiente post...")


if __name__ == "__main__":
    p = Path('/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/project_web/Web_Proyecto/datos/admin')
    for a in list(p.glob('**/reddit_global_dataset.csv')):
        path1 = print(a.as_posix())
        #agregar comillas a path
        CSV_PATH = f'{a.as_posix()}'

        asyncio.run(test_reddit_dataset())